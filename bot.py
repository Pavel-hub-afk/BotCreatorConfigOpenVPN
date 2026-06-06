"""
Telegram-бот для администрирования OpenVPN сервера.

Позволяет:
- Создавать новых пользователей и получать готовый .ovpn конфиг
- Отзывать доступ у существующих пользователей
- Просматривать список активных клиентов

Работает с сервером, на котором OpenVPN уже установлен через Nyr/openvpn-install.
"""

import io
import logging
import os
import re
from functools import wraps

import paramiko
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

TOKEN = os.getenv("TELEGRAM_TOKEN")
SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")

# Comma-separated list of allowed Telegram user IDs
ALLOWED_USER_IDS: set[int] = set(
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
)

EASYRSA_DIR = "/etc/openvpn/server/easy-rsa"
PKI_ISSUED = f"{EASYRSA_DIR}/pki/issued"
PKI_INLINE = f"{EASYRSA_DIR}/pki/inline/private"
COMMON_TXT = "/etc/openvpn/server/client-common.txt"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Sanitize client name exactly like openvpn-install.sh."""
    sanitized = re.sub(r"[^0-9a-zA-Z_-]", "_", name)
    return sanitized if sanitized else "client"


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


def remote_cmd(ssh: paramiko.SSHClient, cmd: str) -> tuple[str, str]:
    """Run a command on the server, return (stdout, stderr)."""
    _, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode().strip(), stderr.read().decode().strip()


def restricted(handler):
    """Decorator: only respond to messages from users in ALLOWED_USER_IDS."""

    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None or user_id not in ALLOWED_USER_IDS:
            logger.warning("Unauthorized access attempt from user_id=%s", user_id)
            if update.message:
                await update.message.reply_text("⛔ Доступ запрещён.")
            return
        return await handler(update, context)

    return wrapper


def client_exists(ssh: paramiko.SSHClient, client: str) -> bool:
    """Check if a client certificate already exists."""
    out, _ = remote_cmd(ssh, f"test -f {PKI_ISSUED}/{client}.crt && echo YES || echo NO")
    return out == "YES"


# ---------------------------------------------------------------------------
# Bot commands
# ---------------------------------------------------------------------------

@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with available commands."""
    await update.message.reply_text(
        "👋 Привет! Я бот для управления OpenVPN сервером.\n\n"
        "📌 Доступные команды:\n"
        "/newclient <имя> — создать пользователя и получить .ovpn конфиг\n"
        "/getconfig <имя> — скачать уже существующий .ovpn\n"
        "/revoke <имя> — отозвать доступ у пользователя\n"
        "/list — показать список активных клиентов"
    )


@restricted
async def newclient(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Create a new OpenVPN client and send the .ovpn config file."""
    if not context.args:
        await update.message.reply_text("❌ Укажите имя клиента.\nПример: /newclient ivanov_ivan_vpn")
        return

    raw_name = " ".join(context.args)
    client = sanitize(raw_name)
    if client != raw_name:
        await update.message.reply_text(f"⚠️ Имя скорректировано: *{raw_name}* → *{client}*")

    status_msg = await update.message.reply_text(f"⏳ Создаю клиента *{client}*...")

    try:
        ssh = ssh_connect()

        # --- Guard: already exists? ---
        if client_exists(ssh, client):
            await status_msg.edit_text(f"❌ Клиент *{client}* уже существует! Используйте /getconfig для скачивания.")
            ssh.close()
            return

        # --- Build certificate ---
        out, err = remote_cmd(
            ssh,
            f"cd {EASYRSA_DIR} && ./easyrsa --batch --days=3650 build-client-full '{client}' nopass",
        )
        if err:
            logger.warning("easyrsa stderr: %s", err)

        # --- Build .ovpn ---
        ovpn_path = f"/tmp/{client}.ovpn"
        remote_cmd(
            ssh,
            f"grep -vh '^#' {COMMON_TXT} {PKI_INLINE}/{client}.inline > {ovpn_path}",
        )

        # --- Download .ovpn via SFTP ---
        sftp = ssh.open_sftp()
        with sftp.open(ovpn_path, "r") as f:
            ovpn_content = f.read().decode()
        sftp.close()
        ssh.exec_command(f"rm -f {ovpn_path}")
        ssh.close()

        # --- Send file to user ---
        file_obj = io.BytesIO(ovpn_content.encode("utf-8"))
        file_obj.name = f"{client}.ovpn"

        await status_msg.edit_text(f"✅ Клиент *{client}* успешно создан!")
        await update.message.reply_document(
            document=file_obj,
            filename=f"{client}.ovpn",
            caption=f"🎉 Конфигурация OpenVPN для *{client}*",
        )

    except Exception as exc:
        logger.exception("Failed to create client %s", client)
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


@restricted
async def getconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Re-download an existing client's .ovpn config."""
    if not context.args:
        await update.message.reply_text("❌ Укажите имя клиента.\nПример: /getconfig ivanov_ivan_vpn")
        return

    client = sanitize(" ".join(context.args))
    status_msg = await update.message.reply_text(f"⏳ Ищу конфиг *{client}*...")

    try:
        ssh = ssh_connect()

        if not client_exists(ssh, client):
            await status_msg.edit_text(f"❌ Клиент *{client}* не найден.")
            ssh.close()
            return

        # Build .ovpn on the fly
        ovpn_path = f"/tmp/{client}.ovpn"
        remote_cmd(
            ssh,
            f"grep -vh '^#' {COMMON_TXT} {PKI_INLINE}/{client}.inline > {ovpn_path}",
        )

        sftp = ssh.open_sftp()
        with sftp.open(ovpn_path, "r") as f:
            ovpn_content = f.read().decode()
        sftp.close()
        ssh.exec_command(f"rm -f {ovpn_path}")
        ssh.close()

        file_obj = io.BytesIO(ovpn_content.encode("utf-8"))
        file_obj.name = f"{client}.ovpn"

        await status_msg.edit_text(f"📥 Отправляю конфиг *{client}*...")
        await update.message.reply_document(
            document=file_obj,
            filename=f"{client}.ovpn",
            caption=f"📎 Конфигурация *{client}*",
        )

    except Exception as exc:
        logger.exception("Failed to get config for %s", client)
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


@restricted
async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke a client certificate."""
    if not context.args:
        await update.message.reply_text("❌ Укажите имя клиента.\nПример: /revoke ivanov_ivan_vpn")
        return

    client = sanitize(" ".join(context.args))
    status_msg = await update.message.reply_text(f"⏳ Отзываю доступ *{client}*...")

    try:
        ssh = ssh_connect()

        if not client_exists(ssh, client):
            await status_msg.edit_text(f"❌ Клиент *{client}* не найден.")
            ssh.close()
            return

        out, err = remote_cmd(
            ssh,
            f"cd {EASYRSA_DIR} && "
            f"./easyrsa --batch revoke '{client}' && "
            f"./easyrsa --batch --days=3650 gen-crl && "
            f"rm -f /etc/openvpn/server/crl.pem && "
            f"cp {EASYRSA_DIR}/pki/crl.pem /etc/openvpn/server/crl.pem",
        )
        if err:
            logger.warning("revoke stderr: %s", err)

        ssh.close()
        await status_msg.edit_text(f"✅ Доступ клиента *{client}* отозван!")

    except Exception as exc:
        logger.exception("Failed to revoke client %s", client)
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


@restricted
async def list_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show valid (non-revoked) clients."""
    status_msg = await update.message.reply_text("⏳ Получаю список клиентов...")

    try:
        ssh = ssh_connect()
        out, _ = remote_cmd(
            ssh,
            f"tail -n +2 {EASYRSA_DIR}/pki/index.txt | grep '^V' | cut -d '=' -f 2",
        )
        ssh.close()

        if not out:
            await status_msg.edit_text("📭 Нет активных клиентов.")
            return

        clients = out.split("\n")
        # first entry is usually "server" — filter it out for user-friendliness
        user_clients = [c for c in clients if c != "server"]
        if not user_clients:
            await status_msg.edit_text("📭 Нет пользовательских клиентов (только серверный).")
            return

        text = f"📋 Активные клиенты ({len(user_clients)}):\n\n" + "\n".join(
            f"• `{c}`" for c in user_clients
        )
        await status_msg.edit_text(text)

    except Exception as exc:
        logger.exception("Failed to list clients")
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    if not TOKEN:
        logger.error("TELEGRAM_TOKEN not set in .env")
        return
    if not SSH_HOST:
        logger.error("SSH_HOST not set in .env")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newclient", newclient))
    app.add_handler(CommandHandler("getconfig", getconfig))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("list", list_clients))

    logger.info("Bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
