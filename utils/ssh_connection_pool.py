"""SSH Connection Pool for parallel file transfers."""
from queue import Queue, Empty
from threading import Lock
from typing import Optional
from handlers.ssh_handler import SSHHandler


class SSHConnectionPool:
    """Pool of SSH connections for parallel operations."""

    def __init__(self, config: dict, pool_size: int = 5):
        """
        Initialize SSH connection pool.

        Args:
            config: SSH configuration dictionary
            pool_size: Number of connections to maintain in pool
        """
        self.config = config
        self.pool_size = pool_size
        self.pool = Queue(maxsize=pool_size)
        self.lock = Lock()
        self._initialized = False

    def initialize(self):
        """Create and connect all handlers in the pool."""
        if self._initialized:
            return

        with self.lock:
            if self._initialized:  # Double-check after acquiring lock
                return

            for _ in range(self.pool_size):
                handler = SSHHandler(
                    host=self.config['host'],
                    path=self.config.get('path', '/'),
                    username=self.config['username'],
                    password=self.config.get('password'),
                    key_file=self.config.get('key_file'),
                    passphrase=self.config.get('passphrase', ''),
                    port=self.config.get('port', 22)
                )
                handler.connect()
                self.pool.put(handler)

            self._initialized = True

    def get_handler(self, timeout: float = 60.0) -> Optional[SSHHandler]:
        """
        Get a handler from the pool.

        Args:
            timeout: Maximum time to wait for an available handler (default 60s)

        Returns:
            SSH handler from pool or None if timeout
        """
        try:
            return self.pool.get(timeout=timeout)
        except Empty:
            return None

    def return_handler(self, handler: SSHHandler):
        """
        Return a handler to the pool.

        Args:
            handler: The handler to return
        """
        if handler:
            self.pool.put(handler)

    def close_all(self):
        """Close all connections in the pool."""
        handlers = []

        # Drain the queue
        while not self.pool.empty():
            try:
                handler = self.pool.get_nowait()
                handlers.append(handler)
            except Empty:
                break

        # Disconnect all handlers
        for handler in handlers:
            try:
                handler.disconnect()
            except Exception:
                pass  # Ignore errors during cleanup

        self._initialized = False
