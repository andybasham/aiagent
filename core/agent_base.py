"""Base class for all agents."""
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any


class CleanOutputFormatter(logging.Formatter):
    """Custom formatter that hides the level name for WARNING messages."""

    def format(self, record):
        # For WARNING level, use a format without levelname
        if record.levelno == logging.WARNING:
            # Temporarily change the format to exclude levelname
            original_format = self._style._fmt
            self._style._fmt = '%(asctime)s - %(name)s - %(message)s'
            result = super().format(record)
            self._style._fmt = original_format
            return result
        else:
            # For all other levels (INFO, ERROR, etc.), use normal format
            return super().format(record)


class AgentBase(ABC):
    """Abstract base class for all agents in the aiagent framework."""

    def __init__(self, config_path: str):
        """
        Initialize the agent with configuration.

        Args:
            config_path: Path to the JSON configuration file
        """
        self.config_path = config_path
        self.config = self._load_config()
        self.logger = self._setup_logger()

    def _load_config(self) -> Dict[str, Any]:
        """Load and validate configuration from JSON file."""
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)

            # Replace {{APPLICATION_NAME}} in all config values
            config = self._replace_application_name_in_config(config)

            self._validate_config(config)
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in configuration file: {e}")

    def _replace_application_name_in_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively replace {{APPLICATION_NAME}} in all config values.

        Args:
            config: Configuration dictionary

        Returns:
            Configuration with {{APPLICATION_NAME}} replaced
        """
        application_name = config.get('application_name', '')

        if not application_name:
            return config  # No replacement needed if application_name is not set

        def replace_in_value(value):
            """Recursively replace {{APPLICATION_NAME}} in a value."""
            if isinstance(value, str):
                return value.replace('{{APPLICATION_NAME}}', application_name)
            elif isinstance(value, dict):
                return {k: replace_in_value(v) for k, v in value.items()}
            elif isinstance(value, list):
                return [replace_in_value(item) for item in value]
            else:
                return value

        # Replace in all config values except 'application_name' itself
        return {
            key: replace_in_value(value) if key != 'application_name' else value
            for key, value in config.items()
        }

    def _setup_logger(self) -> logging.Logger:
        """Set up logger for the agent."""
        logger = logging.getLogger(self.__class__.__name__)

        # Check if verbose mode is enabled in config (default: True for backward compatibility)
        verbose = self.config.get('options', {}).get('verbose', True)

        # Set log level based on verbose setting
        # When verbose=False, only show WARNING and above (hides INFO and DEBUG)
        # When verbose=True, show INFO and above (current behavior)
        logger.setLevel(logging.INFO if verbose else logging.WARNING)

        # Create console handler with custom formatting
        handler = logging.StreamHandler()
        formatter = CleanOutputFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        return logger

    @abstractmethod
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate the configuration structure.

        Args:
            config: The loaded configuration dictionary

        Raises:
            ValueError: If configuration is invalid
        """
        pass

    @abstractmethod
    def run(self) -> None:
        """Execute the agent's main functionality."""
        pass
