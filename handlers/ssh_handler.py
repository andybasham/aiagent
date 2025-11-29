"""Handler for SSH/SFTP connections."""
import os
from pathlib import Path
from typing import Dict, List, Optional
import paramiko
from stat import S_ISDIR

from utils.ssh_utils import load_ssh_private_key


class SSHHandler:
    """Handler for SSH/SFTP connections."""

    def __init__(self, host: str, path: str, username: str,
                 password: Optional[str] = None,
                 key_file: Optional[str] = None,
                 passphrase: Optional[str] = None,
                 port: int = 22):
        """
        Initialize SSH handler.

        Args:
            host: SSH server hostname or IP
            path: Path on the remote server
            username: SSH username
            password: Optional password for authentication
            key_file: Optional path to SSH private key file
            passphrase: Optional passphrase for encrypted private key file
            port: SSH port (default: 22)
        """
        self.host = host
        self.path = path
        self.username = username
        self.password = password
        self.key_file = key_file
        self.passphrase = passphrase
        self.port = port
        self.ssh_client: Optional[paramiko.SSHClient] = None
        self.sftp_client: Optional[paramiko.SFTPClient] = None
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to the SSH server.

        Returns:
            True if connection successful
        """
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Determine authentication method
            if self.key_file:
                # Use key-based authentication
                private_key = load_ssh_private_key(self.key_file, self.passphrase)
                self.ssh_client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    pkey=private_key
                )
            elif self.password:
                # Use password authentication
                self.ssh_client.connect(
                    hostname=self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password
                )
            else:
                raise ValueError("Either password or key_file must be provided")

            self.sftp_client = self.ssh_client.open_sftp()
            self._connected = True
            return True

        except Exception as e:
            raise ConnectionError(f"Failed to connect to SSH server: {e}")

    def disconnect(self) -> None:
        """Disconnect from the SSH server."""
        if self.sftp_client:
            self.sftp_client.close()
        if self.ssh_client:
            self.ssh_client.close()
        self._connected = False

    def _validate_relative_path(self, relative_path: str) -> str:
        """
        Validate and normalize relative path to prevent traversal attacks.

        Args:
            relative_path: The relative path to validate

        Returns:
            Normalized path with forward slashes

        Raises:
            ValueError: If path contains traversal attempts
        """
        # Normalize the path
        normalized = os.path.normpath(relative_path)

        # Check for path traversal attempts
        if normalized.startswith('..') or os.path.isabs(normalized):
            raise ValueError(f"Invalid path: {relative_path} - path traversal not allowed")

        # Ensure no path component is '..'
        parts = Path(normalized).parts
        if '..' in parts:
            raise ValueError(f"Invalid path contains parent reference: {relative_path}")

        # Return with forward slashes for remote paths
        return normalized.replace('\\', '/')

    def list_files(self, recursive: bool = True) -> List[Dict[str, any]]:
        """
        List all files on the remote server.

        Args:
            recursive: If True, list files recursively

        Returns:
            List of file information dictionaries
        """
        if not self._connected or not self.sftp_client:
            raise RuntimeError("Not connected to SSH server")

        files = []
        self._list_files_recursive(self.path, '', files, recursive)
        return files

    def _list_files_recursive(self, base_path: str, relative_path: str,
                              files: List[Dict], recursive: bool) -> None:
        """Recursively list files."""
        # Use forward slashes for remote paths (Linux/Unix)
        if relative_path:
            current_path = f"{base_path}/{relative_path}".replace('\\', '/')
        else:
            current_path = base_path

        try:
            for item in self.sftp_client.listdir_attr(current_path):
                if relative_path:
                    item_relative = f"{relative_path}/{item.filename}".replace('\\', '/')
                else:
                    item_relative = item.filename
                item_full = f"{current_path}/{item.filename}".replace('\\', '/')

                if S_ISDIR(item.st_mode):
                    if recursive:
                        self._list_files_recursive(base_path, item_relative, files, recursive)
                else:
                    files.append({
                        'path': item_relative.replace('\\', '/'),
                        'full_path': item_full.replace('\\', '/'),
                        'size': item.st_size,
                        'modified_time': item.st_mtime,
                        'is_directory': False
                    })
        except Exception as e:
            raise RuntimeError(f"Error listing files in {current_path}: {e}")

    def read_file(self, relative_path: str) -> bytes:
        """Read a file from the remote server."""
        if not self.sftp_client:
            raise RuntimeError("Not connected to SSH server")

        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = os.path.join(self.path, validated_path).replace('\\', '/')
        with self.sftp_client.open(full_path, 'rb') as f:
            return f.read()

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write a file to the remote server."""
        if not self.sftp_client:
            raise RuntimeError("Not connected to SSH server")

        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = os.path.join(self.path, validated_path).replace('\\', '/')

        # Create parent directories if needed
        parent_dir = full_path.rsplit('/', 1)[0] if '/' in full_path else ''
        if parent_dir:
            self._create_remote_directory(parent_dir)

        with self.sftp_client.open(full_path, 'wb') as f:
            f.write(content)

    def delete_file(self, relative_path: str) -> None:
        """Delete a file from the remote server."""
        if not self.sftp_client:
            raise RuntimeError("Not connected to SSH server")

        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = os.path.join(self.path, validated_path).replace('\\', '/')
        self.sftp_client.remove(full_path)

    def delete_directory(self, relative_path: str) -> None:
        """Delete a directory from the remote server."""
        if not self.sftp_client:
            raise RuntimeError("Not connected to SSH server")

        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = os.path.join(self.path, validated_path).replace('\\', '/')
        self._remove_remote_directory(full_path)

    def _remove_remote_directory(self, path: str) -> None:
        """Recursively remove a remote directory."""
        for item in self.sftp_client.listdir_attr(path):
            item_path = f"{path}/{item.filename}".replace('\\', '/')
            if S_ISDIR(item.st_mode):
                self._remove_remote_directory(item_path)
            else:
                self.sftp_client.remove(item_path)
        self.sftp_client.rmdir(path)

    def create_directory(self, relative_path: str) -> None:
        """Create a directory on the remote server."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = os.path.join(self.path, validated_path).replace('\\', '/')
        self._create_remote_directory(full_path)

    def _create_remote_directory(self, path: str) -> None:
        """
        Create directory and parent directories if needed.
        Thread-safe: Handles race conditions when multiple threads try to create the same directory.

        Args:
            path: Remote path to create

        Raises:
            RuntimeError: If not connected to SSH server
        """
        if not self.sftp_client:
            raise RuntimeError("Not connected to SSH server - cannot create directory")

        # Ensure path uses forward slashes
        path = path.replace('\\', '/')

        try:
            self.sftp_client.stat(path)
            # Directory exists, nothing to do
            return
        except FileNotFoundError:
            # Directory doesn't exist, create it
            pass

        # Create parent directory first (recursive)
        parent = path.rsplit('/', 1)[0] if '/' in path else ''
        if parent and parent != '/':
            self._create_remote_directory(parent)

        # Try to create the directory
        try:
            self.sftp_client.mkdir(path)
        except OSError as e:
            # Check if directory now exists (race condition - another thread created it)
            try:
                stat_result = self.sftp_client.stat(path)
                import stat as stat_module
                if stat_module.S_ISDIR(stat_result.st_mode):
                    # Directory exists and is a directory, not a file - this is fine
                    return
            except:
                pass
            # Re-raise the original error if it wasn't a race condition
            raise e
