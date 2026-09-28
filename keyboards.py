from telebot import types

from db import MEAL_TYPE_CODES


def portion_choice_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("⚖️ Я укажу граммы", callback_data="portion_grams"),
        types.InlineKeyboardButton("🤖 Оцени сам", callback_data="portion_estimate"),
    )
    return keyboard


def confirm_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✅ Записать", callback_data="confirm_save"),
        types.InlineKeyboardButton("✏️ Исправить", callback_data="confirm_edit"),
        types.InlineKeyboardButton("❌ Отмена", callback_data="confirm_cancel"),
    )
    return keyboard


def main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("📊 Сегодня", "📜 История")
    keyboard.row("⚖️ Вес", "📈 Отчёт")
    keyboard.row("⚙️ Настройки")
    return keyboard


def history_list_keyboard(meals):
    keyboard = types.InlineKeyboardMarkup()

    for meal_id, date, time, description, calories, meal_type in meals:
        label_time = time or "--:--"
        label_desc = (description or "запись")[:22]
        keyboard.add(
            types.InlineKeyboardButton(
                f"{label_time} · {label_desc} · {calories} ккал",
                callback_data=f"histopen_{meal_id}",
            )
        )

    return keyboard


def history_item_keyboard(meal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "🔄 Приём пищи", callback_data=f"histtype_{meal_id}"
        ),
        types.InlineKeyboardButton("🗑 Удалить", callback_data=f"histdel_{meal_id}"),
    )
    keyboard.add(types.InlineKeyboardButton("« К списку", callback_data="histlist"))
    return keyboard


def meal_type_choice_keyboard(meal_id):
    keyboard = types.InlineKeyboardMarkup()
    buttons = [
        types.InlineKeyboardButton(
            label.capitalize(), callback_data=f"settype_{meal_id}_{code}"
        )
        for code, label in MEAL_TYPE_CODES.items()
    ]
    keyboard.add(*buttons)
    keyboard.add(
        types.InlineKeyboardButton("« Назад", callback_data=f"histback_{meal_id}")
    )
    return keyboard


def report_period_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Неделя", callback_data="reportperiod_week"),
        types.InlineKeyboardButton("Месяц", callback_data="reportperiod_month"),
    )
    keyboard.add(
        types.InlineKeyboardButton("Свой период", callback_data="reportperiod_custom")
    )
    return keyboard


def report_format_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📝 Текст", callback_data="reportformat_text"),
        types.InlineKeyboardButton("🖼 Картинка", callback_data="reportformat_image"),
    )
    return keyboard


# =========================
# НАСТРОЙКИ
# =========================


def settings_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "⏰ Время напоминания", callback_data="settings_reminder"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "🎯 Дневная цель калорий", callback_data="settings_goal"
        )
    )
    return keyboard


def goal_mode_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("✍️ Введу сам", callback_data="goalmode_manual"),
        types.InlineKeyboardButton("🧮 Рассчитать", callback_data="goalmode_calc"),
    )
    keyboard.add(types.InlineKeyboardButton("« Назад", callback_data="settings_back"))
    return keyboard


def gender_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Мужской", callback_data="gender_male"),
        types.InlineKeyboardButton("Женский", callback_data="gender_female"),
    )
    return keyboard


def activity_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton(
            "Низкая — мало или нет спорта", callback_data="activity_low"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "Средняя — тренировки 1-3 раза в неделю", callback_data="activity_medium"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "Высокая — тренировки 4-5 раз в неделю", callback_data="activity_high"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "Очень высокая — спорт почти каждый день",
            callback_data="activity_very_high",
        )
    )
    return keyboard


def goal_type_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("📉 Похудение", callback_data="goaltype_lose")
    )
    keyboard.add(
        types.InlineKeyboardButton(
            "⚖️ Удержание веса", callback_data="goaltype_maintain"
        )
    )
    keyboard.add(
        types.InlineKeyboardButton("📈 Массонабор", callback_data="goaltype_gain")
    )
    return keyboard
