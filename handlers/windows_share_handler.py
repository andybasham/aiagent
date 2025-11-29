"""Handler for Windows network shares."""
import os
from pathlib import Path
from typing import Dict, List, Optional
import shutil


class WindowsShareHandler:
    """Handler for accessing Windows network shares."""

    def __init__(self, path: str, username: Optional[str] = None, password: Optional[str] = None):
        """
        Initialize Windows share handler.

        Args:
            path: UNC path to the share (e.g., \\\\server\\share\\folder)
            username: Optional username for authentication
            password: Optional password for authentication
        """
        self.path = path
        self.username = username
        self.password = password
        self._connected = False

    def connect(self) -> bool:
        """
        Connect to the Windows share.

        Returns:
            True if connection successful
        """
        # For Windows shares, authentication is handled by the OS
        # We just verify the path is accessible
        try:
            if os.path.exists(self.path):
                self._connected = True
                return True
            return False
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Windows share: {e}")

    def disconnect(self) -> None:
        """Disconnect from the Windows share."""
        self._connected = False

    def _validate_relative_path(self, relative_path: str) -> str:
        """
        Validate and normalize relative path to prevent traversal attacks.

        Args:
            relative_path: The relative path to validate

        Returns:
            Normalized path

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

        return normalized

    def list_files(self, recursive: bool = True) -> List[Dict[str, any]]:
        """
        List all files in the share.

        Args:
            recursive: If True, list files recursively

        Returns:
            List of file information dictionaries
        """
        if not self._connected:
            raise RuntimeError("Not connected to share")

        files = []
        base_path = Path(self.path)

        if recursive:
            for item in base_path.rglob('*'):
                if item.is_file():
                    files.append(self._get_file_info(item, base_path))
        else:
            for item in base_path.iterdir():
                if item.is_file():
                    files.append(self._get_file_info(item, base_path))

        return files

    def _get_file_info(self, file_path: Path, base_path: Path) -> Dict[str, any]:
        """Get file information."""
        stat = file_path.stat()
        relative_path = file_path.relative_to(base_path)

        return {
            'path': str(relative_path),
            'full_path': str(file_path),
            'size': stat.st_size,
            'modified_time': stat.st_mtime,
            'is_directory': file_path.is_dir()
        }

    def read_file(self, relative_path: str) -> bytes:
        """Read a file from the share."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = Path(self.path) / validated_path
        with open(full_path, 'rb') as f:
            return f.read()

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write a file to the share."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = Path(self.path) / validated_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with open(full_path, 'wb') as f:
            f.write(content)

    def delete_file(self, relative_path: str) -> None:
        """Delete a file from the share."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = Path(self.path) / validated_path
        if full_path.exists():
            full_path.unlink()

    def delete_directory(self, relative_path: str) -> None:
        """Delete a directory from the share."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = Path(self.path) / validated_path
        if full_path.exists() and full_path.is_dir():
            shutil.rmtree(full_path)

    def create_directory(self, relative_path: str) -> None:
        """Create a directory on the share."""
        # Validate path to prevent traversal attacks
        validated_path = self._validate_relative_path(relative_path)
        full_path = Path(self.path) / validated_path
        full_path.mkdir(parents=True, exist_ok=True)
