"""Path handling utilities for cross-platform compatibility."""
import os
from pathlib import Path


def normalize_path(path: str) -> str:
    """
    Normalize path to use forward slashes for cross-platform comparison.

    Args:
        path: Path to normalize

    Returns:
        Path with forward slashes
    """
    return path.replace('\\', '/')


def validate_relative_path(relative_path: str) -> str:
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


def join_remote_path(*parts: str) -> str:
    """
    Join path components for remote (Unix) systems using forward slashes.

    Args:
        *parts: Path components to join

    Returns:
        Joined path with forward slashes
    """
    return '/'.join(str(p).replace('\\', '/') for p in parts if p)
