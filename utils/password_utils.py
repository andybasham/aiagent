"""Password hashing utilities."""
import bcrypt


def hash_password_bcrypt(plain_password: str) -> str:
    """
    Hash a password using bcrypt compatible with PHP's PASSWORD_DEFAULT.

    Uses cost factor 10 (matching PHP's PASSWORD_DEFAULT) and $2y$ identifier
    for exact compatibility with PHP's password_hash() function.

    Args:
        plain_password: Plain text password

    Returns:
        Bcrypt hashed password string in PHP PASSWORD_DEFAULT format
        Example: $2y$10$xnDBJl/1Q9v4qs42b67pZOTgBFkr6iHJCkDCHdtDARKJrVRq.p2dW

    Raises:
        ValueError: If password is empty
        RuntimeError: If password hashing fails
    """
    if not plain_password:
        raise ValueError("Password cannot be empty")

    try:
        # Generate salt with cost factor 10 (matching PHP's PASSWORD_DEFAULT)
        salt = bcrypt.gensalt(rounds=10)
        hashed = bcrypt.hashpw(plain_password.encode('utf-8'), salt)
        hash_str = hashed.decode('utf-8')

        # Convert $2b$ to $2y$ for exact PHP compatibility
        # Python's bcrypt uses $2b$, PHP uses $2y$, but they're interoperable
        # This ensures exact format match with PHP's password_hash()
        if hash_str.startswith('$2b$'):
            hash_str = '$2y$' + hash_str[4:]

        return hash_str

    except Exception as e:
        raise RuntimeError(f"Failed to hash password securely: {e}") from e
