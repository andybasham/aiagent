"""Agent for uploading files to a remote server."""
import os
from typing import Dict, Any

from core.agent_base import AgentBase
from handlers.ssh_handler import SSHHandler


class AiUploadAgent(AgentBase):
    """Agent that uploads files from the local machine to a remote server."""

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate the upload configuration."""
        if 'server' not in config:
            raise ValueError("Missing required field in config: server")

        server = config['server']
        for field in ['host', 'username', 'path']:
            if field not in server:
                raise ValueError(f"Missing required field in server config: {field}")

        if not server.get('password') and not server.get('key_file'):
            raise ValueError("Server config must have either 'password' or 'key_file'")

        if 'local' not in config or 'path' not in config.get('local', {}):
            raise ValueError("Missing required field in config: local.path")

        if 'files' not in config or not config['files']:
            raise ValueError("Missing or empty 'files' list in config")

    def _create_handler(self) -> SSHHandler:
        """Create an SSH handler from the server config."""
        server = self.config['server']
        return SSHHandler(
            host=server['host'],
            path=server['path'],
            username=server['username'],
            password=server.get('password'),
            key_file=server.get('key_file'),
            passphrase=server.get('passphrase'),
            port=server.get('port', 22)
        )

    def run(self) -> None:
        """Upload files to the remote server."""
        files = self.config['files']
        local_path = self.config['local']['path']
        dry_run = self.config.get('options', {}).get('dry_run', False)

        self.logger.info(f"Upload agent starting - {len(files)} file(s) to upload")
        self.logger.info(f"Server: {self.config['server']['host']}:{self.config['server'].get('port', 22)}")
        self.logger.info(f"Local path: {local_path}")
        self.logger.info(f"Remote path: {self.config['server']['path']}")

        if dry_run:
            self.logger.info("[DRY RUN] Would upload the following files:")
            for f in files:
                local_file = os.path.join(local_path, f)
                exists = os.path.exists(local_file)
                status = "" if exists else " [NOT FOUND]"
                self.logger.info(f"  {f}{status}")
            return

        handler = self._create_handler()
        try:
            self.logger.info("Connecting to server...")
            handler.connect()
            self.logger.info("Connected successfully")

            uploaded = 0
            failed = 0

            for filename in files:
                local_file = os.path.join(local_path, filename)

                if not os.path.exists(local_file):
                    self.logger.error(f"  File not found: {local_file}")
                    failed += 1
                    continue

                try:
                    size_kb = os.path.getsize(local_file) / 1024
                    self.logger.info(f"Uploading: {filename} ({size_kb:.1f} KB)")
                    with open(local_file, 'rb') as f:
                        content = f.read()
                    handler.write_file(filename, content)

                    # Set permissions to rw-r----- (640) and ownership to andy:www-data
                    remote_file = f"{self.config['server']['path']}/{filename}".replace('\\', '/')
                    handler.sftp_client.chmod(remote_file, 0o640)
                    stdin, stdout, stderr = handler.ssh_client.exec_command(f"sudo -S chown andy:www-data '{remote_file}'")
                    password = self.config['server'].get('password', '')
                    if password:
                        stdin.write(password + '\n')
                        stdin.flush()
                    stdout.channel.recv_exit_status()

                    self.logger.info(f"  Uploaded to: {remote_file}")
                    uploaded += 1
                except Exception as e:
                    self.logger.error(f"  Failed to upload {filename}: {e}")
                    failed += 1

            self.logger.info(f"Upload complete - {uploaded} uploaded, {failed} failed")

        finally:
            handler.disconnect()
            self.logger.info("Disconnected from server")
