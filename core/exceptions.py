"""Custom exception hierarchy for aiagent framework."""


class AgentError(Exception):
    """Base exception for all agent-related errors."""
    pass


class ConfigurationError(AgentError):
    """Raised when configuration is invalid."""
    pass


class ConnectionError(AgentError):
    """Raised when connection to remote system fails."""
    pass


class FileOperationError(AgentError):
    """Raised when file operations fail."""
    pass


class DatabaseError(AgentError):
    """Raised when database operations fail."""
    pass


class ValidationError(AgentError):
    """Raised when validation fails."""
    pass


class PathTraversalError(ValidationError):
    """Raised when path traversal is detected."""
    pass
