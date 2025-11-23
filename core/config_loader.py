"""Configuration loader utilities."""
import json
from pathlib import Path
from typing import Dict, Any


class ConfigLoader:
    """Utility class for loading and managing configurations."""

    @staticmethod
    def load(config_path: str) -> Dict[str, Any]:
        """
        Load configuration from a JSON file.

        Args:
            config_path: Path to the configuration file

        Returns:
            Dictionary containing the configuration

        Raises:
            FileNotFoundError: If config file doesn't exist
            ValueError: If JSON is invalid
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")

        try:
            with open(path, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration: {e}")

    @staticmethod
    def save(config: Dict[str, Any], config_path: str) -> None:
        """
        Save configuration to a JSON file.

        Args:
            config: Configuration dictionary
            config_path: Path to save the configuration
        """
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=2)
