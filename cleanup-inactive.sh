#!/bin/bash
# ---------------------------------------------------------------------------
# cleanup-inactive.sh
# Находит VPN-клиентов, не активных более 180 дней, и отзывает их сертификаты.
#
# Использование:
#   ./cleanup-inactive.sh --dry-run    только показать неактивных
#   ./cleanup-inactive.sh              отозвать всех неактивных
# ---------------------------------------------------------------------------

set -euo pipefail

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

EASYRSA_DIR="/etc/openvpn/server/easy-rsa"
PKI_INDEX="$EASYRSA_DIR/pki/index.txt"
TRACKER_DIR="/var/lib/ovpn-tracker"
INACTIVE_DAYS=180

# Проверяем, что директория трекера существует
if [ ! -d "$TRACKER_DIR" ]; then
    echo "ERROR: tracker dir $TRACKER_DIR not found" >&2
    exit 1
fi

# Получаем список валидных клиентов из PKI (исключаем серверный)
VALID_CLIENTS=$(tail -n +2 "$PKI_INDEX" 2>/dev/null | grep '^V' | cut -d '=' -f 2 | grep -v '^server$' | sort)

if [ -z "$VALID_CLIENTS" ]; then
    echo "No valid clients found."
    exit 0
fi

INACTIVE_COUNT=0
NOW=$(date +%s)
CUTOFF=$((NOW - INACTIVE_DAYS * 86400))

echo "=== Проверка неактивных клиентов (более $INACTIVE_DAYS дней) ==="
echo "Дата проверки: $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

while IFS= read -r client; do
    [ -z "$client" ] && continue

    TRACK_FILE="$TRACKER_DIR/${client}.last_seen"

    if [ ! -f "$TRACK_FILE" ]; then
        # Нет файла трекера — никогда не подключался за время наблюдения
        echo "НЕАКТИВЕН: $client (нет данных о подключениях)"
        INACTIVE_COUNT=$((INACTIVE_COUNT + 1))

        if [ "$DRY_RUN" = false ]; then
            echo "  -> Отзываю сертификат..."
            cd "$EASYRSA_DIR"
            ./easyrsa --batch revoke "$client" >/dev/null 2>&1 || echo "  -> ОШИБКА отзыва $client"
        fi
    else
        # Проверяем возраст файла
        FILE_MTIME=$(stat -c '%Y' "$TRACK_FILE" 2>/dev/null || echo 0)
        if [ "$FILE_MTIME" -lt "$CUTOFF" ]; then
            LAST_SEEN=$(date -d "@$FILE_MTIME" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "неизвестно")
            echo "НЕАКТИВЕН: $client (последний раз: $LAST_SEEN)"
            INACTIVE_COUNT=$((INACTIVE_COUNT + 1))

            if [ "$DRY_RUN" = false ]; then
                echo "  -> Отзываю сертификат..."
                cd "$EASYRSA_DIR"
                ./easyrsa --batch revoke "$client" >/dev/null 2>&1 || echo "  -> ОШИБКА отзыва $client"
            fi
        fi
    fi
done <<< "$VALID_CLIENTS"

# Если был реальный отзыв — обновляем CRL
if [ "$DRY_RUN" = false ] && [ "$INACTIVE_COUNT" -gt 0 ]; then
    echo ""
    echo "=== Обновление CRL ==="
    cd "$EASYRSA_DIR"
    ./easyrsa --batch --days=3650 gen-crl >/dev/null 2>&1
    rm -f /etc/openvpn/server/crl.pem
    cp "$EASYRSA_DIR/pki/crl.pem" /etc/openvpn/server/crl.pem
    echo "CRL обновлён."
fi

echo ""
echo "=== Итого ==="
echo "Всего клиентов: $(echo "$VALID_CLIENTS" | wc -l)"
echo "Неактивных: $INACTIVE_COUNT"

if [ "$DRY_RUN" = true ]; then
    echo "Режим: DRY-RUN (отзыв не выполнялся)"
else
    echo "Режим: реальный отзыв"
fi
