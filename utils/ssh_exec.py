"""SSH command execution utilities."""
import paramiko
from typing import Tuple, Optional


def execute_ssh_command(
    ssh_client: paramiko.SSHClient,
    command: str,
    check_exit_code: bool = True,
    timeout: Optional[int] = None
) -> Tuple[int, str, str]:
    """
    Execute command via SSH and return exit code, stdout, stderr.

    Args:
        ssh_client: Connected SSH client
        command: Command to execute
        check_exit_code: If True, raise error on non-zero exit
        timeout: Optional command timeout in seconds

    Returns:
        Tuple of (exit_code, stdout, stderr)

    Raises:
        RuntimeError: If command fails and check_exit_code is True
    """
    stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()

    stdout_text = stdout.read().decode('utf-8', errors='replace')
    stderr_text = stderr.read().decode('utf-8', errors='replace')

    if check_exit_code and exit_code != 0:
        raise RuntimeError(
            f"Command failed (exit {exit_code}): {command}\nSTDERR: {stderr_text}"
        )

    return exit_code, stdout_text, stderr_text
