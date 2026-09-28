from datetime import datetime

WEEKDAYS_RU = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]


def format_date_ddmmyyyy(date_str):
    """'YYYY-MM-DD' -> 'ДД-ММ-ГГГГ'"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%d-%m-%Y")


def format_date_with_weekday(date_str):
    """'YYYY-MM-DD' -> 'День недели, ДД-ММ-ГГГГ'"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAYS_RU[date_obj.weekday()]
    return f"{weekday}, {date_obj.strftime('%d-%m-%Y')}"
