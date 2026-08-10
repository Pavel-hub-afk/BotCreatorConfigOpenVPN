#!/bin/bash
# ---------------------------------------------------------------------------
# client-info.sh <client_name>
# Выводит полную информацию по клиенту в секционном формате.
# Секции: CERT, ENDDATE, ISSUED, IPP, STATUS, TRACKER
# ---------------------------------------------------------------------------
set -euo pipefail

CLIENT="${1:-}"
if [ -z "$CLIENT" ]; then
    echo "ERROR: client name required" >&2
    exit 1
fi

EASYRSA_DIR="/etc/openvpn/server/easy-rsa"
PKI="$EASYRSA_DIR/pki"
IPP_FILE="/etc/openvpn/server/ipp.txt"
STATUS_FILE="/var/log/openvpn/status.log"
TRACKER_FILE="/var/lib/ovpn-tracker/${CLIENT}.last_seen"

echo "---CERT---"
grep "/CN=$CLIENT$" "$PKI/index.txt" 2>/dev/null || echo "N/A"

echo "---ENDDATE---"
openssl x509 -in "$PKI/issued/$CLIENT.crt" -enddate -noout 2>/dev/null | cut -d'=' -f2 || echo "N/A"

echo "---ISSUED---"
openssl x509 -in "$PKI/issued/$CLIENT.crt" -startdate -noout 2>/dev/null | cut -d'=' -f2 || echo "N/A"

echo "---IPP---"
grep "^$CLIENT," "$IPP_FILE" 2>/dev/null || echo "N/A"

echo "---STATUS---"
grep "^CLIENT_LIST,$CLIENT," "$STATUS_FILE" 2>/dev/null || echo "N/A"

echo "---TRACKER---"
if [ -f "$TRACKER_FILE" ]; then
    stat -c %Y "$TRACKER_FILE"
else
    echo "never"
fi
