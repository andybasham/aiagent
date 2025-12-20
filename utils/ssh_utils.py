"""SSH utilities for connection handling."""
from typing import Optional
import paramiko


def load_ssh_private_key(key_file: str, passphrase: Optional[str] = None) -> paramiko.PKey:
    """
    Load SSH private key with support for multiple key types.
    Tries Ed25519, RSA, ECDSA, and DSS key types in order.

    Args:
        key_file: Path to private key file
        passphrase: Optional passphrase for encrypted keys

    Returns:
        Loaded private key

    Raises:
        ValueError: If key cannot be loaded with any supported type
    """
    passphrase = passphrase if passphrase else None

    key_types = [
        ('Ed25519', paramiko.Ed25519Key),
        ('RSA', paramiko.RSAKey),
        ('ECDSA', paramiko.ECDSAKey),
    ]
    # DSSKey was removed in paramiko 3.0+ (DSS/DSA keys are deprecated)
    if hasattr(paramiko, 'DSSKey'):
        key_types.append(('DSS', paramiko.DSSKey))

    last_error = None
    for key_name, key_class in key_types:
        try:
            return key_class.from_private_key_file(key_file, password=passphrase)
        except Exception as e:
            last_error = e
            continue

    raise ValueError(f"Failed to load private key from {key_file}. Last error: {last_error}")
