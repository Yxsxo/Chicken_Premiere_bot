"""Тексты сообщений бота. Здесь только сборка строк — без Telegram и без базы."""

from datetime import datetime, timedelta

import clock

WEEKDAYS_RU = [
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
]

MEAL_TYPE_EMOJI = {
    "завтрак": "🍳",
    "обед": "🍲",
    "ужин": "🍽",
    "перекус": "🍎",
}

MEAL_TYPE_ORDER = ["завтрак", "обед", "ужин", "перекус"]

DAY_OFFSET_LABELS = {1: "вчера", 2: "позавчера"}


# =========================
# ДАТЫ
# =========================


def format_date_ddmmyyyy(date_str):
    """'YYYY-MM-DD' -> 'ДД-ММ-ГГГГ'"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    return date_obj.strftime("%d-%m-%Y")


def format_date_with_weekday(date_str):
    """'YYYY-MM-DD' -> 'День недели, ДД-ММ-ГГГГ'"""
    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAYS_RU[date_obj.weekday()]
    return f"{weekday}, {date_obj.strftime('%d-%m-%Y')}"


def format_day_offset(day_offset):
    """1 -> 'вчера (Воскресенье, 27-09-2026)'"""
    date_str = (clock.now() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    return f"{DAY_OFFSET_LABELS[day_offset]} ({format_date_with_weekday(date_str)})"


# =========================
# РАЗБОР ЕДЫ
# =========================


def format_item_line(item):
    """'Рыба — 150 г — 180 ккал' или 'Яйцо — 3 шт (150 г) — 235 ккал'"""
    amount = f"{item['grams']} г"

    if item["quantity"] != amount:
        amount = f"{item['quantity']} ({amount})"

    return f"{item['name'].capitalize()} — {amount} — {item['kcal']} ккал"


def format_food_result(result, header, meal_type=None, day_offset=0):
    lines = [header, ""]

    for item in result["items"]:
        lines.append(f"• {format_item_line(item)}")

    if not result["items"]:
        lines.append("(список пуст — добавь продукт или отмени)")

    # :g убирает лишний ноль: 20.0 → 20, а 45.5 остаётся 45.5
    lines.append(
        f"\n≈ {result['total_kcal']} ккал\n"
        f"Б: {result['total_protein']:g} г · "
        f"Ж: {result['total_fat']:g} г · "
        f"У: {result['total_carbs']:g} г"
    )

    if meal_type:
        lines.append(f"\n🍽 Приём пищи: {meal_type}")

    if day_offset:
        lines.append(f"📅 Запишу на {format_day_offset(day_offset)}")

    return "\n".join(lines)


def build_description(result):
    parts = [f"{item['name']} {item['quantity']}" for item in result["items"]]
    return ", ".join(parts)


# =========================
# ИСТОРИЯ
# =========================


def format_meal_detail(meal, items=None):
    meal_id, date, time, description, calories, meal_type = meal
    emoji = MEAL_TYPE_EMOJI.get(meal_type, "❓")
    time_str = time or "--:--"
    type_str = meal_type or "не указан"

    if items:
        desc = "\n".join(f"• {format_item_line(item)}" for item in items)
    else:
        desc = description or "Старая запись"

    return (
        f"{emoji} {time_str}\n"
        f"📅 {format_date_with_weekday(date)}\n\n"
        f"{desc}\n\n"
        f"Итого: {calories} ккал\n"
        f"Приём пищи: {type_str}"
    )


# =========================
# ИТОГИ ДНЯ
# =========================


def progress_bar(value, goal, width=10):
    """██████░░░░ — сколько от цели уже набрано."""
    if not goal:
        return ""

    filled = min(width, round(value / goal * width))
    return "█" * filled + "░" * (width - filled)


def format_day_summary(totals, daily_goal, protein_goal=None):
    """Калории с прогресс-баром и БЖУ. totals = (kcal, protein, fat, carbs)."""
    kcal, protein, fat, carbs = totals
    percent = round(kcal / daily_goal * 100) if daily_goal else 0
    remaining = daily_goal - kcal

    if remaining >= 0:
        left_line = f"🎯 Осталось: {remaining} ккал"
    else:
        left_line = f"⚠️ Перебор: {-remaining} ккал"

    protein_part = f"{protein} / {protein_goal} г" if protein_goal else f"{protein} г"

    return (
        f"🔥 {kcal} / {daily_goal} ккал\n"
        f"{progress_bar(kcal, daily_goal)} {percent}%\n"
        f"{left_line}\n"
        f"🥩 Б: {protein_part} · Ж: {fat} г · У: {carbs} г"
    )


def format_today_text(meals, totals, daily_goal, protein_goal=None):
    text = f"📊 {format_date_with_weekday(clock.today_str())}:\n\n"

    if not meals:
        text += "Записей пока нет.\n\n"
    else:
        grouped = {key: [] for key in MEAL_TYPE_ORDER}
        unspecified = []

        for meal_time, description, calories, meal_type in meals:
            if description is None:
                description = "Старая запись"

            if meal_type in grouped:
                grouped[meal_type].append((description, calories))
            else:
                unspecified.append((description, calories))

        for meal_type in MEAL_TYPE_ORDER:
            items = grouped[meal_type]
            if not items:
                continue

            text += f"{MEAL_TYPE_EMOJI[meal_type]} {meal_type.capitalize()}:\n"

            for description, calories in items:
                text += f"— {description} — {calories} ккал\n"

            text += "\n"

        if unspecified:
            text += "❓ Приём пищи не указан:\n"
            for description, calories in unspecified:
                text += f"— {description} — {calories} ккал\n"
            text += "\n"

    return text + format_day_summary(totals, daily_goal, protein_goal)


def format_short_summary(totals, daily_goal):
    """Короткий итог после записи: 'Сегодня: 1450 / 2200 ккал' + полоска."""
    kcal = totals[0]
    remaining = daily_goal - kcal
    left = f"осталось {remaining}" if remaining >= 0 else f"перебор {-remaining}"

    return (
        f"Сегодня: {kcal} / {daily_goal} ккал\n"
        f"{progress_bar(kcal, daily_goal)} {left}"
    )


# =========================
# ВЕС
# =========================


def format_weight_change(diff):
    """-0.4 -> '−0.4 кг', 0 -> 'без изменений'"""
    if abs(diff) < 0.05:
        return "без изменений"

    sign = "+" if diff > 0 else "−"
    return f"{sign}{abs(diff):.1f} кг"
