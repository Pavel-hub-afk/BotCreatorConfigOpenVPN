"""
Форматирование: даты, байты, время последней активности.
"""

import datetime
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def fmt_bytes(n: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n} {unit}"
        n //= 1024
    return f"{n} TB"


def fmt_last_seen(ts_str: str) -> str:
    """Форматирует строку с timestamp или 'never' в читаемую дату последней активности."""
    now_dt = datetime.datetime.now(MSK)
    now_ts = now_dt.timestamp()

    if ts_str == "never":
        return "⚠️ ни разу не подключался"

    ts = int(ts_str)
    ago_days = int((now_ts - ts) / 86400)
    last_dt = datetime.datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M")

    if ago_days == 0:
        return f"🟢 сегодня ({last_dt})"
    elif ago_days < 7:
        return f"{ago_days} дн. назад ({last_dt})"
    elif ago_days < 180:
        return f"{ago_days} дн. назад ({last_dt})"
    else:
        return f"🔴 {ago_days} дн. назад ({last_dt})"


def fmt_last_seen_plain(ts_str: str) -> str:
    """Форматирует timestamp/'never' для /info (без эмодзи, с MSK)."""
    if ts_str == "never":
        return "нет данных"

    ts = int(ts_str)
    ago_days = int((datetime.datetime.now(MSK).timestamp() - ts) / 86400)
    last_dt = datetime.datetime.fromtimestamp(ts, tz=MSK).strftime("%d.%m.%Y %H:%M")

    if ago_days == 0:
        return f"сегодня {last_dt} (MSK)"
    else:
        return f"{ago_days} дн. назад ({last_dt} MSK)"
