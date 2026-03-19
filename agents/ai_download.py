"""Agent for downloading files from a remote server."""
import os
from typing import Dict, Any

from core.agent_base import AgentBase
from handlers.ssh_handler import SSHHandler


class AiDownloadAgent(AgentBase):
    """Agent that downloads files from a remote server to the local machine."""

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate the download configuration."""
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
        """Download files from the remote server."""
        files = self.config['files']
        local_path = self.config['local']['path']
        dry_run = self.config.get('options', {}).get('dry_run', False)
        overwrite = self.config.get('options', {}).get('overwrite_existing', True)

        self.logger.info(f"Download agent starting - {len(files)} file(s) to download")
        self.logger.info(f"Server: {self.config['server']['host']}:{self.config['server'].get('port', 22)}")
        self.logger.info(f"Remote path: {self.config['server']['path']}")
        self.logger.info(f"Local path: {local_path}")

        if dry_run:
            self.logger.info("[DRY RUN] Would download the following files:")
            for f in files:
                self.logger.info(f"  {f}")
            return

        # Ensure local directory exists
        os.makedirs(local_path, exist_ok=True)

        handler = self._create_handler()
        try:
            self.logger.info("Connecting to server...")
            handler.connect()
            self.logger.info("Connected successfully")

            downloaded = 0
            skipped = 0
            failed = 0

            for filename in files:
                local_file = os.path.join(local_path, os.path.basename(filename))

                if not overwrite and os.path.exists(local_file):
                    self.logger.info(f"Skipped (exists): {filename}")
                    skipped += 1
                    continue

                try:
                    self.logger.info(f"Downloading: {filename}")
                    content = handler.read_file(filename)
                    with open(local_file, 'wb') as f:
                        f.write(content)
                    size_kb = len(content) / 1024
                    self.logger.info(f"  Saved: {local_file} ({size_kb:.1f} KB)")
                    downloaded += 1
                except Exception as e:
                    self.logger.error(f"  Failed to download {filename}: {e}")
                    failed += 1

            self.logger.info(f"Download complete - {downloaded} downloaded, {skipped} skipped, {failed} failed")

        finally:
            handler.disconnect()
            self.logger.info("Disconnected from server")
