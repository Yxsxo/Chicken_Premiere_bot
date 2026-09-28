import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

# Часовой пояс пользователей бота. На хостинге часы сервера обычно в UTC,
# поэтому «сегодня» и время напоминаний считаем в этом поясе, а не по серверу.
TIMEZONE = ZoneInfo(os.getenv("BOT_TIMEZONE", "Europe/Moscow"))


def now():
    """Текущие дата и время в часовом поясе бота."""
    return datetime.now(TIMEZONE)


def today_str():
    """Сегодняшняя дата в формате базы: 'YYYY-MM-DD'."""
    return now().strftime("%Y-%m-%d")
