#!/bin/bash
# ---------------------------------------------------------------------------
# client-list.sh
# Выводит список всех валидных клиентов с датами последней активности.
# Формат: client|timestamp или client|never
# ---------------------------------------------------------------------------
set -euo pipefail

EASYRSA_DIR="/etc/openvpn/server/easy-rsa"
TRACKER_DIR="/var/lib/ovpn-tracker"

for client in $(tail -n +2 "$EASYRSA_DIR/pki/index.txt" | grep '^V' | cut -d '=' -f 2 | grep -v '^server$'); do
    track_file="$TRACKER_DIR/${client}.last_seen"
    if [ -f "$track_file" ]; then
        echo "$client|$(stat -c %Y "$track_file")"
    else
        echo "$client|never"
    fi
done
