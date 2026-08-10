"""
Telegram-бот для администрирования OpenVPN сервера.

Позволяет:
- Создавать новых пользователей и получать готовый .ovpn конфиг
- Отзывать доступ у существующих пользователей
- Просматривать список активных клиентов

Работает с сервером, на котором OpenVPN уже установлен через Nyr/openvpn-install.
"""

import io
import re
from functools import wraps

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from config import (
    TOKEN, SSH_HOST, ALLOWED_USER_IDS,
    EASYRSA_DIR, COMMON_TXT, PKI_INLINE, SCRIPTS_DIR,
    logger,
)
from ssh_utils import ssh_session, remote_cmd, client_exists
from formatting import fmt_bytes, fmt_last_seen, fmt_last_seen_plain


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sanitize(name: str) -> str:
    """Sanitize client name exactly like openvpn-install.sh."""
    sanitized = re.sub(r"[^0-9a-zA-Z_-]", "_", name)
    return sanitized if sanitized else "client"


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
        "/list — показать список активных клиентов\n"
        "/info <имя> — полная информация о клиенте"
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
        with ssh_session() as ssh:
            if client_exists(ssh, client):
                await status_msg.edit_text(f"❌ Клиент *{client}* уже существует! Используйте /getconfig для скачивания.")
                return

            out, err = remote_cmd(
                ssh,
                f"cd {EASYRSA_DIR} && ./easyrsa --batch --days=3650 build-client-full '{client}' nopass",
            )
            if err:
                logger.warning("easyrsa stderr: %s", err)

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
        with ssh_session() as ssh:
            if not client_exists(ssh, client):
                await status_msg.edit_text(f"❌ Клиент *{client}* не найден.")
                return

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
        with ssh_session() as ssh:
            if not client_exists(ssh, client):
                await status_msg.edit_text(f"❌ Клиент *{client}* не найден.")
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

        await status_msg.edit_text(f"✅ Доступ клиента *{client}* отозван!")

    except Exception as exc:
        logger.exception("Failed to revoke client %s", client)
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


@restricted
async def list_clients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show valid (non-revoked) clients with last connection date."""
    status_msg = await update.message.reply_text("⏳ Получаю список клиентов...")

    try:
        with ssh_session() as ssh:
            out, _ = remote_cmd(ssh, f"{SCRIPTS_DIR}/client-list.sh")

        if not out:
            await status_msg.edit_text("📭 Нет активных клиентов.")
            return

        lines = []
        for entry in out.split("\n"):
            if "|" not in entry:
                continue
            client, ts_str = entry.split("|", 1)
            lines.append(f"• `{client}` — {fmt_last_seen(ts_str)}")

        if not lines:
            await status_msg.edit_text("📭 Нет пользовательских клиентов (только серверный).")
            return

        text = f"📋 Клиенты ({len(lines)}):\n\n" + "\n".join(lines)
        await status_msg.edit_text(text)

    except Exception as exc:
        logger.exception("Failed to list clients")
        await status_msg.edit_text(f"❌ Ошибка: {exc}")


@restricted
async def client_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed info about a specific client."""
    if not context.args:
        await update.message.reply_text("❌ Укажите имя клиента.\nПример: /info akinin_julia_vpn")
        return

    client = sanitize(" ".join(context.args))
    status_msg = await update.message.reply_text(f"⏳ Собираю информацию о *{client}*...")

    try:
        with ssh_session() as ssh:
            out, _ = remote_cmd(ssh, f"{SCRIPTS_DIR}/client-info.sh {client}")

        # Парсим секционный вывод
        sections = {}
        current_section = None
        for line in out.split("\n"):
            if line.startswith("---") and line.endswith("---"):
                current_section = line.strip("-")
                sections[current_section] = []
            elif current_section:
                sections[current_section].append(line)

        def _section(name: str) -> str:
            return "\n".join(sections.get(name, []))

        cert_line = _section("CERT")
        enddate_str = _section("ENDDATE")
        issued_str = _section("ISSUED")
        ipp_line = _section("IPP")
        status_line = _section("STATUS")
        tracker_raw = _section("TRACKER")

        lines = [f"Информация о клиенте: `{client}`", ""]

        # Сертификат
        if cert_line and cert_line != "N/A":
            parts = cert_line.split()
            if parts and parts[0] == "V":
                lines.append("Сертификат: ✅ валиден")
            elif parts and parts[0] == "R":
                lines.append("Сертификат: ❌ отозван")
            else:
                lines.append(f"Сертификат: {cert_line}")
        else:
            lines.append("Сертификат: ❌ не найден")

        if issued_str and issued_str != "N/A":
            lines.append(f"Выпущен: {issued_str}")
        if enddate_str and enddate_str != "N/A":
            lines.append(f"Истекает: {enddate_str}")

        # IP
        if ipp_line and ipp_line != "N/A":
            parts = ipp_line.split(",")
            if len(parts) >= 3:
                lines.append(f"Виртуальный IP: {parts[1]} / {parts[2]}")
            elif len(parts) >= 2:
                lines.append(f"Виртуальный IP: {parts[1]}")

        # Статус подключения
        if status_line and status_line != "N/A":
            parts = status_line.split(",")
            if len(parts) >= 6:
                real_addr = parts[2] if len(parts) > 2 else "?"
                bytes_recv = int(parts[5]) if len(parts) > 5 else 0
                bytes_sent = int(parts[6]) if len(parts) > 6 else 0
                lines.append("")
                lines.append("Сейчас в сети: ✅ да")
                lines.append(f"Реальный IP: {real_addr.split(':')[0] if ':' in real_addr else real_addr}")
                lines.append(f"Трафик: {fmt_bytes(bytes_recv)} принято / {fmt_bytes(bytes_sent)} отправлено")
                if len(parts) >= 8:
                    lines.append(f"В сети с: {parts[7]}")
        else:
            lines.append("")
            lines.append("Сейчас в сети: ❌ нет")

        lines.append(f"Последняя активность: {fmt_last_seen_plain(tracker_raw)}")

        await status_msg.edit_text("\n".join(lines))

    except Exception as exc:
        logger.exception("Failed to get info for %s", client)
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

    async def set_bot_commands(app_obj: Application) -> None:
        commands = [
            BotCommand("start", "Приветствие и список команд"),
            BotCommand("newclient", "Создать клиента и получить .ovpn конфиг"),
            BotCommand("getconfig", "Скачать готовый .ovpn конфиг"),
            BotCommand("revoke", "Отозвать сертификат клиента"),
            BotCommand("list", "Список активных клиентов"),
            BotCommand("info", "Полная информация о клиенте"),
        ]
        await app_obj.bot.set_my_commands(commands)
        logger.info("Bot commands menu has been set")

    app.post_init = set_bot_commands

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newclient", newclient))
    app.add_handler(CommandHandler("getconfig", getconfig))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("list", list_clients))
    app.add_handler(CommandHandler("info", client_info))

    logger.info("Bot polling started")
    app.run_polling()


if __name__ == "__main__":
    main()
