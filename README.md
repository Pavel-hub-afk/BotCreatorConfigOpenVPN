# OpenVPN Telegram Bot

Telegram-бот для удалённого администрирования OpenVPN-сервера. Позволяет создавать, отзывать и просматривать VPN-клиентов прямо из Telegram.

## Возможности

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и список доступных команд |
| `/newclient <имя>` | Создать клиента и получить `.ovpn` конфиг |
| `/getconfig <имя>` | Повторно скачать готовый `.ovpn` |
| `/revoke <имя>` | Отозвать сертификат клиента |
| `/list` | Список клиентов с датой последнего подключения (MSK) |

При вводе `/` в Telegram отображается выпадающее меню команд с описаниями.

## Требования

- Python 3.10+
- OpenVPN-сервер, установленный через [Nyr/openvpn-install](https://github.com/Nyr/openvpn-install)
- Доступ к серверу по SSH (пароль или ключ)

## Установка на сервер

### 1. Клонирование

```bash
mkdir -p /opt/ovpn-bot
cd /opt/ovpn-bot
git clone https://github.com/Pavel-hub-afk/BotCreatorConfigOpenVPN.git .
```

### 2. Виртуальное окружение и зависимости

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Конфигурация

Создать `.env` в корне проекта:

```env
TELEGRAM_TOKEN=123456:ABC-DEF...    # токен от @BotFather
SSH_HOST=192.168.1.100              # IP OpenVPN-сервера (127.0.0.1 — если локально)
SSH_USER=root
SSH_PASSWORD=your_password          # или SSH_KEY_PATH=/root/.ssh/id_rsa
# SSH_KEY_PATH=/root/.ssh/id_rsa
ALLOWED_USER_IDS=123456789          # свой Telegram ID (узнать у @userinfobot)
```

### 4. Автозапуск через systemd

Создать `/etc/systemd/system/ovpn-bot.service`:

```ini
[Unit]
Description=OpenVPN Telegram Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/ovpn-bot
ExecStart=/opt/ovpn-bot/venv/bin/python /opt/ovpn-bot/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Запустить:

```bash
systemctl daemon-reload
systemctl enable --now ovpn-bot
systemctl status ovpn-bot
```

## Управление ботом

| Действие | Команда |
|----------|---------|
| Статус | `systemctl status ovpn-bot` |
| Остановить | `systemctl stop ovpn-bot` |
| Запустить | `systemctl start ovpn-bot` |
| Перезапустить | `systemctl restart ovpn-bot` |
| Логи (real-time) | `journalctl -u ovpn-bot -f` |
| Логи (последние 50) | `journalctl -u ovpn-bot -n 50` |
| Занимаемое место | `journalctl -u ovpn-bot --disk-usage` |

## Отслеживание активности клиентов

Бот показывает дату последнего подключения каждого клиента в команде `/list`. Для этого на сервере работает инфраструктура:

```
OpenVPN ──► /var/log/openvpn/status.log (обновляется каждые 15 сек)
                │
Cron (5 мин) ──► /opt/ovpn-bot/track-connections.sh
                │
                ▼
     /var/lib/ovpn-tracker/*.last_seen
                │
                ▼
     /list — дата последнего подключения (MSK)
```

### Компоненты на сервере

| Компонент | Путь | Описание |
|-----------|------|----------|
| Статус-лог OpenVPN | `/var/log/openvpn/status.log` | Пишется OpenVPN, список текущих подключений |
| Трекер | `/opt/ovpn-bot/track-connections.sh` | Читает status.log, создаёт `.last_seen` файлы |
| Маркеры активности | `/var/lib/ovpn-tracker/*.last_seen` | Файл-маркер для каждого подключавшегося клиента |

### Настройка OpenVPN

В `/etc/openvpn/server/server.conf` добавлена строка:

```
status /var/log/openvpn/status.log 15
```

### Cron

```
*/5 * * * * /opt/ovpn-bot/track-connections.sh
```

## Памятка: внесение изменений

```
┌─────────────────────────────────────────────────────┐
│  1. ЛОКАЛЬНО                                        │
│     Правишь код → тестируешь                        │
│     git add -A                                      │
│     git commit -m "описание правок"                 │
│     git push origin master                          │
│                                                     │
│  2. НА СЕРВЕРЕ                                      │
│     ssh root@твой_сервер                            │
│     cd /opt/ovpn-bot                                │
│     git pull origin master                          │
│                                                     │
│     # Если обновился requirements.txt:              │
│     source venv/bin/activate                        │
│     pip install -r requirements.txt                 │
│     deactivate                                      │
│                                                     │
│     systemctl restart ovpn-bot                      │
│     systemctl status ovpn-bot                       │
│     journalctl -u ovpn-bot -n 10                    │
└─────────────────────────────────────────────────────┘
```

## Где хранятся данные

Список клиентов живёт **на OpenVPN-сервере** в файле:

```
/etc/openvpn/server/easy-rsa/pki/index.txt
```

Сам бот базу не ведёт — все операции (создание, отзыв) выполняются через SSH-команды EasyRSA на сервере.

## Безопасность

- Доступ к боту ограничен по Telegram user ID (`ALLOWED_USER_IDS` в `.env`)
- Чужие пользователи получают ответ `⛔ Доступ запрещён.`
- Все попытки неавторизованного доступа логируются
- `.env` с паролями не попадает в git (добавлен в `.gitignore`)
