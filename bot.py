import os
from datetime import datetime, timedelta

import telebot
from dotenv import load_dotenv

import db
import claude_client
import keyboards
import state
import reports
import reminders
import formatting
import calc

# =========================
# НАСТРОЙКИ
# =========================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if TOKEN is None:
    raise ValueError("Не найден BOT_TOKEN в файле .env")

bot = telebot.TeleBot(TOKEN)

MEAL_TYPE_EMOJI = {
    "завтрак": "🍳",
    "обед": "🍲",
    "ужин": "🍽",
    "перекус": "🍎",
}

MEAL_TYPE_ORDER = ["завтрак", "обед", "ужин", "перекус"]


def ensure_registered(user_id, chat_id):
    db.register_user(user_id, chat_id)


# =========================
# ФОРМАТИРОВАНИЕ
# =========================


def format_food_result(data, estimated, meal_type_label=None):
    header = "🤖 Я оценил порцию так:\n" if estimated else "🍽 Вот что получилось:\n"
    lines = [header]

    for item in data["items"]:
        lines.append(f"{item['name']} — {item['grams']} г — {item['kcal']} ккал")

    lines.append(
        f"\n≈ {data['total_kcal']} ккал"
        f"\nБ: {data['total_protein']} г"
        f"\nЖ: {data['total_fat']} г"
        f"\nУ: {data['total_carbs']} г"
    )

    if meal_type_label:
        lines.append(f"\n🍽 Приём пищи: {meal_type_label} (указано вами)")

    return "\n".join(lines)


def build_description(data):
    parts = [f"{item['name']} {item['quantity']}" for item in data["items"]]
    return ", ".join(parts)


def format_meal_detail(meal):
    meal_id, date, time, description, calories, meal_type = meal
    emoji = MEAL_TYPE_EMOJI.get(meal_type, "❓")
    time_str = time or "--:--"
    desc = description or "Старая запись"
    type_str = meal_type or "не указан"

    return (
        f"{emoji} {time_str}\n"
        f"📅 {formatting.format_date_with_weekday(date)}\n"
        f"{desc}\n"
        f"{calories} ккал\n"
        f"Приём пищи: {type_str}"
    )


def format_today_text(meals, total, remaining, daily_goal):
    today_date_str = datetime.now().strftime("%Y-%m-%d")
    text = f"📊 {formatting.format_date_with_weekday(today_date_str)}:\n\n"

    if not meals:
        text += "Записей пока нет.\n"
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

            emoji = MEAL_TYPE_EMOJI[meal_type]
            text += f"{emoji} {meal_type.capitalize()}:\n"

            for description, calories in items:
                text += f"— {description} — {calories} ккал\n"

            text += "\n"

        if unspecified:
            text += "❓ Приём пищи не указан:\n"
            for description, calories in unspecified:
                text += f"— {description} — {calories} ккал\n"
            text += "\n"

    text += f"🔥 Всего: {total} / {daily_goal} ккал\n" f"🎯 Осталось: {remaining} ккал"

    return text


# =========================
# ИСТОРИЯ (список)
# =========================


def show_history_list(chat_id, user_id, message_id=None):
    meals = db.get_last_meals(user_id, limit=15)

    if not meals:
        text = "Записей пока нет."
        keyboard = None
    else:
        text = "📜 Последние записи (нажми, чтобы изменить или удалить):"
        keyboard = keyboards.history_list_keyboard(meals)

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


# =========================
# ВЕС, ОТЧЁТЫ, НАСТРОЙКИ — вспомогательные
# =========================


def ask_weight(chat_id, user_id):
    state.clear_state(user_id)
    state.set_state(user_id, stage="waiting_weight")
    bot.send_message(chat_id, "Напиши свой текущий вес числом, например: 78.4")


def ask_report_period(chat_id, user_id):
    state.clear_state(user_id)
    bot.send_message(
        chat_id, "За какой период?", reply_markup=keyboards.report_period_keyboard()
    )


def show_settings_menu(chat_id, user_id):
    state.clear_state(user_id)
    bot.send_message(
        chat_id, "⚙️ Настройки:", reply_markup=keyboards.settings_menu_keyboard()
    )


# =========================
# /start
# =========================


@bot.message_handler(commands=["start"])
def start(message):
    ensure_registered(message.from_user.id, message.chat.id)
    bot.reply_to(
        message,
        "Привет 👋\n\n"
        "Напиши мне число калорий (например: 450) или опиши, что ты съел, обычными словами.\n"
        "Можно сразу указать приём пищи: «на завтрак съел 3 яйца» — если не указать, "
        "определю сам по времени сообщения.\n\n"
        "Кнопки внизу помогут посмотреть историю, отчёты, записать вес и настроить бота под себя.",
        reply_markup=keyboards.main_menu_keyboard(),
    )


# =========================
# /today
# =========================


@bot.message_handler(commands=["today"])
def today(message):
    ensure_registered(message.from_user.id, message.chat.id)
    user_id = message.from_user.id

    meals = db.get_today_meals(user_id)
    total = db.get_today_calories(user_id)
    daily_goal = db.get_daily_goal(user_id)
    remaining = daily_goal - total

    bot.reply_to(message, format_today_text(meals, total, remaining, daily_goal))


# =========================
# /history, /weight, /report, /settings
# =========================


@bot.message_handler(commands=["history"])
def history_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    show_history_list(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["weight"])
def weight_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    ask_weight(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["report"])
def report_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    ask_report_period(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["settings"])
def settings_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    show_settings_menu(message.chat.id, message.from_user.id)


# =========================
# ОБЫЧНЫЕ СООБЩЕНИЯ
# =========================


@bot.message_handler(
    func=lambda message: message.text is not None and not message.text.startswith("/")
)
def text_message(message):
    user_id = message.from_user.id
    ensure_registered(user_id, message.chat.id)
    text = message.text.strip()

    # --- Кнопки постоянного меню ---
    if text == "📊 Сегодня":
        today(message)
        return

    if text == "📜 История":
        show_history_list(message.chat.id, user_id)
        return

    if text == "⚖️ Вес":
        ask_weight(message.chat.id, user_id)
        return

    if text == "📈 Отчёт":
        ask_report_period(message.chat.id, user_id)
        return

    if text == "⚙️ Настройки":
        show_settings_menu(message.chat.id, user_id)
        return

    current_state = state.get_state(user_id)
    stage = current_state.get("stage")

    # --- Прислал граммы после "Я укажу граммы" ---
    if stage == "waiting_grams":
        bot.send_chat_action(message.chat.id, "typing")

        food_text = current_state.get("food_text")
        explicit_meal_type = current_state.get("explicit_meal_type")

        data = claude_client.analyze_food(food_text, grams_text=text)

        if data is None:
            bot.reply_to(
                message, "Не получилось посчитать 🤔 Попробуй написать граммы ещё раз."
            )
            return

        state.set_state(user_id, stage="waiting_confirmation", result=data)

        label = explicit_meal_type.capitalize() if explicit_meal_type else None

        bot.reply_to(
            message,
            format_food_result(data, estimated=False, meal_type_label=label),
            reply_markup=keyboards.confirm_keyboard(),
        )
        return

    # --- Ввод веса ---
    if stage == "waiting_weight":
        try:
            weight = float(text.replace(",", "."))
        except ValueError:
            bot.reply_to(
                message, "Не получилось распознать число. Напиши вес так: 78.4"
            )
            return

        db.add_weight(user_id, weight)
        state.clear_state(user_id)

        bot.reply_to(message, f"⚖️ Записал вес: {weight} кг")
        return

    # --- Ввод своего периода для отчёта ---
    if stage == "waiting_custom_period":
        try:
            start_str, end_str = text.split("-")
            start_date = datetime.strptime(start_str.strip(), "%d.%m.%Y").date()
            end_date = datetime.strptime(end_str.strip(), "%d.%m.%Y").date()
        except ValueError:
            bot.reply_to(
                message, "Не получилось распознать даты. Формат: 01.09.2026-14.09.2026"
            )
            return

        state.clear_state(user_id)
        state.set_state(
            user_id,
            stage="waiting_report_format",
            report_start=start_date.isoformat(),
            report_end=end_date.isoformat(),
        )
        bot.reply_to(
            message,
            "Какой формат отчёта?",
            reply_markup=keyboards.report_format_keyboard(),
        )
        return

    # --- Настройка времени напоминания ---
    if stage == "waiting_reminder_time":
        try:
            hour_str, minute_str = text.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
            if not (0 <= hour < 24 and 0 <= minute < 60):
                raise ValueError
        except ValueError:
            bot.reply_to(
                message, "Не получилось распознать время. Формат: ЧЧ:ММ, например 21:00"
            )
            return

        db.set_reminder_time(user_id, hour, minute)
        state.clear_state(user_id)

        bot.reply_to(message, f"⏰ Готово! Буду напоминать в {hour:02d}:{minute:02d}.")
        return

    # --- Ручной ввод дневной цели ---
    if stage == "waiting_manual_goal":
        if not text.isdigit():
            bot.reply_to(message, "Напиши цель числом, например: 2200")
            return

        goal = int(text)
        db.set_daily_goal(user_id, goal)
        state.clear_state(user_id)

        bot.reply_to(message, f"🎯 Готово! Дневная цель: {goal} ккал.")
        return

    # --- Форма расчёта цели: вес ---
    if stage == "waiting_goal_weight":
        try:
            weight = float(text.replace(",", "."))
        except ValueError:
            bot.reply_to(message, "Напиши вес числом в кг, например: 78.5")
            return

        state.set_state(user_id, stage="waiting_goal_height", goal_weight=weight)
        bot.reply_to(message, "Какой у тебя рост в см?")
        return

    # --- Форма расчёта цели: рост ---
    if stage == "waiting_goal_height":
        try:
            height = float(text.replace(",", "."))
        except ValueError:
            bot.reply_to(message, "Напиши рост числом в см, например: 175")
            return

        state.set_state(user_id, stage="waiting_goal_age", goal_height=height)
        bot.reply_to(message, "Сколько тебе лет?")
        return

    # --- Форма расчёта цели: возраст (дальше — кнопки) ---
    if stage == "waiting_goal_age":
        if not text.isdigit():
            bot.reply_to(message, "Напиши возраст числом, например: 27")
            return

        state.set_state(user_id, stage="waiting_goal_gender_button", goal_age=int(text))
        bot.reply_to(message, "Какой пол?", reply_markup=keyboards.gender_keyboard())
        return

    # --- Обычное число калорий ---
    if text.isdigit():
        calories = int(text)

        db.add_meal(user_id, "Ручная запись", calories)

        total = db.get_today_calories(user_id)
        daily_goal = db.get_daily_goal(user_id)
        remaining = daily_goal - total

        state.clear_state(user_id)

        bot.reply_to(
            message,
            f"✅ Записал {calories} ккал\n\n"
            f"Сегодня: {total} / {daily_goal} ккал\n"
            f"Осталось: {remaining} ккал",
        )
        return

    # --- Новое описание еды ---
    explicit_meal_type = db.detect_explicit_meal_type(text)

    state.clear_state(user_id)
    state.set_state(
        user_id,
        stage="waiting_portion_choice",
        food_text=text,
        explicit_meal_type=explicit_meal_type,
    )

    bot.reply_to(
        message,
        "Как считаем порцию?",
        reply_markup=keyboards.portion_choice_keyboard(),
    )


# =========================
# НАЖАТИЯ НА КНОПКИ
# =========================


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    ensure_registered(user_id, call.message.chat.id)
    current_state = state.get_state(user_id)
    data = call.data

    if data == "portion_grams":
        state.set_state(user_id, stage="waiting_grams")
        bot.edit_message_text(
            "Напиши вес каждого продукта в граммах, например:\n"
            "рис 180 г, курица 200 г, овощи 100 г",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "portion_estimate":
        bot.edit_message_text(
            "🤖 Считаю...", call.message.chat.id, call.message.message_id
        )

        food_text = current_state.get("food_text")
        explicit_meal_type = current_state.get("explicit_meal_type")

        result = claude_client.analyze_food(food_text)

        if result is None:
            bot.send_message(
                call.message.chat.id,
                "Не получилось разобрать это как еду 🤔 Попробуй переформулировать.",
            )
            state.clear_state(user_id)
        else:
            state.set_state(user_id, stage="waiting_confirmation", result=result)

            label = explicit_meal_type.capitalize() if explicit_meal_type else None

            bot.send_message(
                call.message.chat.id,
                format_food_result(result, estimated=True, meal_type_label=label),
                reply_markup=keyboards.confirm_keyboard(),
            )

    elif data == "confirm_save":
        result = current_state.get("result")
        explicit_meal_type = current_state.get("explicit_meal_type")

        if result is None:
            bot.answer_callback_query(call.id, "Что-то пошло не так, попробуй заново")
            return

        description = build_description(result)

        db.add_meal(
            user_id,
            description,
            result["total_kcal"],
            protein=result["total_protein"],
            fat=result["total_fat"],
            carbs=result["total_carbs"],
            meal_type=explicit_meal_type,
        )

        state.clear_state(user_id)

        total = db.get_today_calories(user_id)
        daily_goal = db.get_daily_goal(user_id)
        remaining = daily_goal - total

        bot.edit_message_text(
            f"✅ Записано!\n\nСегодня: {total} / {daily_goal} ккал\nОсталось: {remaining} ккал",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "confirm_edit":
        state.clear_state(user_id)
        bot.edit_message_text(
            "Хорошо, напиши заново, что ты съел.",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "confirm_cancel":
        state.clear_state(user_id)
        bot.edit_message_text(
            "❌ Отменено", call.message.chat.id, call.message.message_id
        )

    # --- История ---

    elif data == "histlist":
        show_history_list(call.message.chat.id, user_id, call.message.message_id)

    elif data.startswith("histopen_"):
        meal_id = int(data.split("_")[1])
        meal = db.get_meal_by_id(meal_id, user_id)

        if meal is None:
            bot.answer_callback_query(
                call.id, "Запись не найдена (возможно, уже удалена)"
            )
            show_history_list(call.message.chat.id, user_id, call.message.message_id)
            return

        bot.edit_message_text(
            format_meal_detail(meal),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.history_item_keyboard(meal_id),
        )

    elif data.startswith("histtype_"):
        meal_id = int(data.split("_")[1])
        bot.edit_message_text(
            "Выбери правильный приём пищи:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.meal_type_choice_keyboard(meal_id),
        )

    elif data.startswith("histback_"):
        meal_id = int(data.split("_")[1])
        meal = db.get_meal_by_id(meal_id, user_id)
        bot.edit_message_text(
            format_meal_detail(meal),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.history_item_keyboard(meal_id),
        )

    elif data.startswith("settype_"):
        _, meal_id_str, code = data.split("_")
        meal_id = int(meal_id_str)
        new_type = db.MEAL_TYPE_CODES.get(code)

        db.update_meal_type(meal_id, user_id, new_type)
        meal = db.get_meal_by_id(meal_id, user_id)

        bot.edit_message_text(
            "✅ Обновлено!\n\n" + format_meal_detail(meal),
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.history_item_keyboard(meal_id),
        )

    elif data.startswith("histdel_"):
        meal_id = int(data.split("_")[1])
        db.delete_meal(meal_id, user_id)

        bot.answer_callback_query(call.id, "Удалено")
        show_history_list(call.message.chat.id, user_id, call.message.message_id)
        return

    # --- Отчёты ---

    elif data == "reportperiod_week":
        state.clear_state(user_id)
        today_date = datetime.now().date()
        start = today_date - timedelta(days=6)
        state.set_state(
            user_id,
            stage="waiting_report_format",
            report_start=start.isoformat(),
            report_end=today_date.isoformat(),
        )
        bot.edit_message_text(
            "Какой формат отчёта?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.report_format_keyboard(),
        )

    elif data == "reportperiod_month":
        state.clear_state(user_id)
        today_date = datetime.now().date()
        start = today_date - timedelta(days=29)
        state.set_state(
            user_id,
            stage="waiting_report_format",
            report_start=start.isoformat(),
            report_end=today_date.isoformat(),
        )
        bot.edit_message_text(
            "Какой формат отчёта?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.report_format_keyboard(),
        )

    elif data == "reportperiod_custom":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_custom_period")
        bot.edit_message_text(
            "Напиши период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ\nНапример: 01.09.2026-14.09.2026",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "reportformat_text":
        start = current_state.get("report_start")
        end = current_state.get("report_end")

        report_text = reports.build_text_report(user_id, start, end)
        state.clear_state(user_id)

        bot.edit_message_text(
            report_text, call.message.chat.id, call.message.message_id
        )

    elif data == "reportformat_image":
        start = current_state.get("report_start")
        end = current_state.get("report_end")

        bot.edit_message_text(
            "📈 Строю график...", call.message.chat.id, call.message.message_id
        )

        image_path = reports.build_image_report(user_id, start, end)
        state.clear_state(user_id)

        if image_path is None:
            bot.send_message(
                call.message.chat.id,
                "За этот период записей нет — картинку строить не из чего.",
            )
        else:
            with open(image_path, "rb") as photo:
                bot.send_photo(call.message.chat.id, photo)

    # --- Настройки ---

    elif data == "settings_reminder":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_reminder_time")

        current_hour, current_minute = db.get_reminder_time(user_id)
        bot.edit_message_text(
            f"Сейчас напоминание приходит в {current_hour:02d}:{current_minute:02d}.\n"
            "Напиши новое время в формате ЧЧ:ММ, например 21:00",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "settings_goal":
        current_goal = db.get_daily_goal(user_id)
        bot.edit_message_text(
            f"Сейчас дневная цель: {current_goal} ккал.\nКак хочешь её задать?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.goal_mode_keyboard(),
        )

    elif data == "settings_back":
        bot.edit_message_text(
            "⚙️ Настройки:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.settings_menu_keyboard(),
        )

    elif data == "goalmode_manual":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_manual_goal")
        bot.edit_message_text(
            "Напиши свою дневную цель числом (в ккал), например: 2200",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data == "goalmode_calc":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_goal_weight")
        bot.edit_message_text(
            "Небольшая форма, чтобы рассчитать цель под тебя.\n\nКакой у тебя вес в кг?",
            call.message.chat.id,
            call.message.message_id,
        )

    elif data.startswith("gender_"):
        gender = data.split("_")[1]  # male / female
        state.set_state(user_id, goal_gender=gender)

        bot.edit_message_text(
            "Какой у тебя уровень активности?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.activity_keyboard(),
        )

    elif data.startswith("activity_"):
        activity = data[len("activity_") :]  # low / medium / high / very_high
        state.set_state(user_id, goal_activity=activity)

        bot.edit_message_text(
            "И последнее — какая у тебя цель?",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=keyboards.goal_type_keyboard(),
        )

    elif data.startswith("goaltype_"):
        goal_type = data[len("goaltype_") :]  # lose / maintain / gain

        weight = current_state.get("goal_weight")
        height = current_state.get("goal_height")
        age = current_state.get("goal_age")
        gender = current_state.get("goal_gender")
        activity = current_state.get("goal_activity")

        if None in (weight, height, age, gender, activity):
            bot.answer_callback_query(
                call.id, "Что-то потерялось, начни заново через Настройки"
            )
            state.clear_state(user_id)
            return

        goal = calc.calculate_daily_goal(
            weight, height, age, gender, activity, goal_type
        )

        db.set_daily_goal(user_id, goal)
        state.clear_state(user_id)

        bot.edit_message_text(
            f"🎯 Готово! Рассчитанная дневная цель: {goal} ккал.\n\n"
            "Если захочешь поменять — снова зайди в ⚙️ Настройки.",
            call.message.chat.id,
            call.message.message_id,
        )

    bot.answer_callback_query(call.id)


# =========================
# ЗАПУСК
# =========================

bot.set_my_commands(
    [
        telebot.types.BotCommand("start", "Начать"),
        telebot.types.BotCommand("today", "Сегодня"),
        telebot.types.BotCommand("history", "История записей"),
        telebot.types.BotCommand("weight", "Записать вес"),
        telebot.types.BotCommand("report", "Отчёт за период"),
        telebot.types.BotCommand("settings", "Настройки"),
    ]
)

reminders.start_reminders(bot)

print("Бот запущен!")

bot.infinity_polling(skip_pending=True)
