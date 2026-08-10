"""
SSH-утилиты: подключение, выполнение команд, контекстный менеджер.
"""

from contextlib import contextmanager

import paramiko

from config import SSH_HOST, SSH_USER, SSH_PASSWORD, SSH_KEY_PATH, PKI_ISSUED


def ssh_connect() -> paramiko.SSHClient:
    """Open an SSH connection to the OpenVPN server."""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs: dict = {"hostname": SSH_HOST, "username": SSH_USER, "timeout": 10}
    if SSH_KEY_PATH:
        kwargs["key_filename"] = SSH_KEY_PATH
    elif SSH_PASSWORD:
        kwargs["password"] = SSH_PASSWORD
    else:
        raise RuntimeError("Either SSH_PASSWORD or SSH_KEY_PATH must be set in .env")

    ssh.connect(**kwargs)
    return ssh


@contextmanager
def ssh_session():
    """Context manager: автоматически закрывает SSH-соединение."""
    ssh = ssh_connect()
    try:
        yield ssh
    finally:
        ssh.close()


def remote_cmd(ssh: paramiko.SSHClient, cmd: str) -> tuple[str, str]:
    """Run a command on the server, return (stdout, stderr)."""
    _, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode().strip(), stderr.read().decode().strip()


def client_exists(ssh: paramiko.SSHClient, client: str) -> bool:
    """Check if a client certificate already exists."""
    out, _ = remote_cmd(ssh, f"test -f {PKI_ISSUED}/{client}.crt && echo YES || echo NO")
    return out == "YES"
