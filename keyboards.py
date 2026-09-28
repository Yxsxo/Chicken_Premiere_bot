from telebot import types

import formatting
from db import MEAL_TYPE_CODES


def _button(text, callback_data):
    return types.InlineKeyboardButton(text, callback_data=callback_data)


def main_menu_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("📊 Сегодня", "📜 История")
    keyboard.row("🔁 Повторить", "⚖️ Вес")
    keyboard.row("📈 Отчёт", "⚙️ Настройки")
    return keyboard


# =========================
# НОВАЯ ЗАПИСЬ И РЕДАКТОР
# =========================


def portion_choice_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("⚖️ Я укажу граммы", "portion_grams"),
        _button("🤖 Оцени сам", "portion_estimate"),
    )
    return keyboard


def confirm_keyboard(save_label="✅ Записать"):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button(save_label, "confirm_save"),
        _button("✏️ Исправить", "confirm_edit"),
        _button("❌ Отмена", "confirm_cancel"),
    )
    return keyboard


def editor_keyboard(items, save_label="✅ Записать"):
    """Каждый продукт — кнопка. Нажал — можно изменить вес или убрать."""
    keyboard = types.InlineKeyboardMarkup()

    for index, item in enumerate(items):
        keyboard.add(_button(formatting.format_item_line(item), f"edit_item_{index}"))

    keyboard.add(_button("➕ Добавить продукт", "edit_add"))

    buttons = [_button("❌ Отмена", "confirm_cancel")]
    if items:
        buttons.insert(0, _button(save_label, "confirm_save"))
    keyboard.add(*buttons)

    return keyboard


def item_actions_keyboard(index):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("⚖️ Изменить вес", f"edit_grams_{index}"),
        _button("🗑 Убрать", f"edit_remove_{index}"),
    )
    keyboard.add(_button("« Назад", "edit_back"))
    return keyboard


def editor_back_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("« Назад", "edit_back"))
    return keyboard


# =========================
# ИСТОРИЯ И ПОВТОР
# =========================


def history_list_keyboard(meals):
    keyboard = types.InlineKeyboardMarkup()

    for meal_id, date, time, description, calories, meal_type in meals:
        label_time = time or "--:--"
        label_desc = (description or "запись")[:22]
        keyboard.add(
            _button(
                f"{label_time} · {label_desc} · {calories} ккал", f"histopen_{meal_id}"
            )
        )

    return keyboard


def history_item_keyboard(meal_id, has_items):
    keyboard = types.InlineKeyboardMarkup()

    if has_items:
        keyboard.add(_button("✏️ Изменить состав", f"histedit_{meal_id}"))

    keyboard.add(
        _button("🔄 Приём пищи", f"histtype_{meal_id}"),
        _button("🔁 Ещё раз сегодня", f"repeat_{meal_id}"),
    )
    keyboard.add(
        _button("🗑 Удалить", f"histdel_{meal_id}"),
        _button("« К списку", "histlist"),
    )
    return keyboard


def delete_confirm_keyboard(meal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("🗑 Да, удалить", f"histdelok_{meal_id}"),
        _button("Отмена", f"histback_{meal_id}"),
    )
    return keyboard


def meal_type_choice_keyboard(meal_id):
    keyboard = types.InlineKeyboardMarkup()
    buttons = [
        _button(label.capitalize(), f"settype_{meal_id}_{code}")
        for code, label in MEAL_TYPE_CODES.items()
    ]
    keyboard.add(*buttons)
    keyboard.add(_button("« Назад", f"histback_{meal_id}"))
    return keyboard


def repeat_list_keyboard(meals):
    keyboard = types.InlineKeyboardMarkup()

    for meal_id, description, calories in meals:
        keyboard.add(_button(f"{description[:40]} · {calories} ккал", f"repeat_{meal_id}"))

    return keyboard


def undo_keyboard(meal_id):
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("↩️ Отменить", f"undo_{meal_id}"))
    return keyboard


# =========================
# ВЕС И ОТЧЁТЫ
# =========================


def weight_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("📈 График веса", "weight_chart"))
    return keyboard


def report_period_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("Неделя", "reportperiod_week"),
        _button("Месяц", "reportperiod_month"),
    )
    keyboard.add(_button("Свой период", "reportperiod_custom"))
    return keyboard


def report_format_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("📝 Текст", "reportformat_text"),
        _button("🖼 Картинка", "reportformat_image"),
    )
    return keyboard


# =========================
# НАСТРОЙКИ
# =========================


def settings_menu_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("⏰ Время напоминания", "settings_reminder"))
    keyboard.add(_button("🎯 Дневная цель калорий", "settings_goal"))
    keyboard.add(_button("🥩 Цель по белку", "settings_protein"))
    return keyboard


def goal_mode_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("✍️ Введу сам", "goalmode_manual"),
        _button("🧮 Рассчитать", "goalmode_calc"),
    )
    keyboard.add(_button("« Назад", "settings_back"))
    return keyboard


def gender_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        _button("Мужской", "gender_male"),
        _button("Женский", "gender_female"),
    )
    return keyboard


def activity_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("Низкая — мало или нет спорта", "activity_low"))
    keyboard.add(_button("Средняя — тренировки 1-3 раза в неделю", "activity_medium"))
    keyboard.add(_button("Высокая — тренировки 4-5 раз в неделю", "activity_high"))
    keyboard.add(
        _button("Очень высокая — спорт почти каждый день", "activity_very_high")
    )
    return keyboard


def goal_type_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(_button("📉 Похудение", "goaltype_lose"))
    keyboard.add(_button("⚖️ Удержание веса", "goaltype_maintain"))
    keyboard.add(_button("📈 Массонабор", "goaltype_gain"))
    return keyboard
