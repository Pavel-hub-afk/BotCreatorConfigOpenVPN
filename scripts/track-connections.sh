#!/bin/bash
# ---------------------------------------------------------------------------
# track-connections.sh
# Считывает OpenVPN status.log и для каждого подключённого клиента
# обновляет файл-маркер .last_seen в /var/lib/ovpn-tracker/
#
# Запуск: каждые 5 минут через cron
# ---------------------------------------------------------------------------

set -euo pipefail

STATUS_FILE="/var/log/openvpn/status.log"
TRACKER_DIR="/var/lib/ovpn-tracker"

# Проверяем, что статус-файл существует и не пуст
if [ ! -f "$STATUS_FILE" ] || [ ! -s "$STATUS_FILE" ]; then
    exit 0
fi

# Извлекаем строки с данными между заголовками CLIENT_LIST и ROUTING_TABLE
# Формат: CLIENT_LIST,<имя>,<real_addr>,...
# Имя клиента — второе поле после запятой
sed -n '/^HEADER,CLIENT_LIST/,/^HEADER,ROUTING_TABLE/p' "$STATUS_FILE" \
    | grep '^CLIENT_LIST,' \
    | awk -F',' '$2 != "UNDEF"' \
    | cut -d',' -f2 \
    | while IFS= read -r client; do
        [ -z "$client" ] && continue
        touch "$TRACKER_DIR/${client}.last_seen"
    done
