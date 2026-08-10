"""
Конфигурация Telegram-бота для администрирования OpenVPN сервера.
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
ALLOWED_USER_IDS: set[int] = set(
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
)

# --- SSH ---
SSH_HOST = os.getenv("SSH_HOST")
SSH_USER = os.getenv("SSH_USER", "root")
SSH_PASSWORD = os.getenv("SSH_PASSWORD")
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH")

# --- OpenVPN paths (server-side) ---
EASYRSA_DIR = "/etc/openvpn/server/easy-rsa"
PKI_ISSUED = f"{EASYRSA_DIR}/pki/issued"
PKI_INLINE = f"{EASYRSA_DIR}/pki/inline/private"
COMMON_TXT = "/etc/openvpn/server/client-common.txt"

# --- Bot scripts directory (server-side) ---
SCRIPTS_DIR = "/opt/ovpn-bot/scripts"

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
