import os
import logging
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import telebot
from telebot.apihelper import ApiTelegramException
from dotenv import load_dotenv

import db
import claude_client
import keyboards
import state
import reports
import reminders
import formatting
import nutrition
import calc
import clock

# =========================
# ЛОГИ
# =========================

logger = logging.getLogger("bot")


def setup_logging():
    """Пишем и в консоль, и в bot.log. Когда файл дорастёт до 1 МБ, он станет
    bot.log.1, а старые копии дальше bot.log.3 удаляются — диск не забьётся."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            ),
        ],
    )
    # httpx пишет в INFO каждый запрос к API — это шум, оставляем только проблемы
    logging.getLogger("httpx").setLevel(logging.WARNING)


class LogExceptionHandler(telebot.ExceptionHandler):
    """Любая непойманная ошибка в обработчиках попадает в лог, а бот работает дальше."""

    def handle(self, exception):
        logger.error("Ошибка в обработчике", exc_info=exception)
        return True


# =========================
# НАСТРОЙКИ
# =========================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

if TOKEN is None:
    raise ValueError("Не найден BOT_TOKEN в файле .env")

bot = telebot.TeleBot(TOKEN, exception_handler=LogExceptionHandler())

LLM_UNAVAILABLE_TEXT = (
    "😔 Сервис подсчёта сейчас не отвечает. Попробуй ещё раз через минуту."
)

NOT_FOOD_TEXT = "Не получилось разобрать это как еду 🤔 Попробуй переформулировать."

# Заголовок черновика зависит от того, откуда пришёл результат
DRAFT_HEADERS = {
    "estimate": "🤖 Я оценил порцию так:",
    "grams": "🍽 Вот что получилось:",
    "photo": "📷 Вот что я вижу на фото:",
}

EDITOR_HINT = (
    "✏️ Нажми на продукт, чтобы изменить вес или убрать его.\n"
    "Или напиши исправление словами: «рыбы было 200 г, хлеба не было»."
)

# Кнопки, которые относятся к черновику приёма пищи
DRAFT_CALLBACK_PREFIXES = ("portion_", "confirm_", "edit_")


# =========================
# ОБЩИЕ ПОМОЩНИКИ
# =========================


def ensure_registered(user_id, chat_id):
    db.register_user(user_id, chat_id)


def parse_number(text, min_value, max_value):
    """Число из текста пользователя ("78,4" тоже годится) в разумных границах.
    Если это не число или оно вне границ — None."""
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None

    # nan и бесконечность эту проверку тоже не пройдут
    if not (min_value <= value <= max_value):
        return None

    return value


def edit(chat_id, message_id, text, reply_markup=None):
    """edit_message_text, который не падает, если текст и кнопки не изменились."""
    try:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=reply_markup)
    except ApiTelegramException as error:
        if "message is not modified" not in str(error):
            raise


def remove_keyboard(chat_id, message_id):
    """Убирает кнопки у сообщения. Если не вышло (кнопок уже нет) — не страшно."""
    if message_id is None:
        return

    try:
        bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
    except ApiTelegramException:
        pass


def answer(call, text=None):
    """Ответ на нажатие кнопки (убирает «часики»). Повторный ответ молча пропускаем."""
    try:
        bot.answer_callback_query(call.id, text)
    except ApiTelegramException:
        pass


def today_short_summary(user_id):
    return formatting.format_short_summary(
        db.get_today_totals(user_id), db.get_daily_goal(user_id)
    )


# =========================
# ЧЕРНОВИК ПРИЁМА ПИЩИ
# =========================
# Черновик — результат разбора еды, который ещё не записан.
# Он живёт в состоянии: result (продукты и итоги), source (откуда пришёл),
# explicit_meal_type, day_offset, editing_meal_id (если правим запись из истории)
# и draft_message_id — сообщение, в котором сейчас показан черновик.


def draft_text(st, editing):
    if editing:
        header = EDITOR_HINT
    elif st.get("editing_meal_id"):
        header = "✏️ Изменение записи:"
    else:
        header = DRAFT_HEADERS.get(st.get("source"), DRAFT_HEADERS["grams"])

    return formatting.format_food_result(
        st["result"], header, st.get("explicit_meal_type"), st.get("day_offset", 0)
    )


def draft_keyboard(st, editing):
    save_label = "💾 Сохранить" if st.get("editing_meal_id") else "✅ Записать"

    if editing:
        return keyboards.editor_keyboard(st["result"]["items"], save_label)

    return keyboards.confirm_keyboard(save_label)


def show_draft(chat_id, user_id, editing, message_id=None):
    """Показывает черновик: результат с кнопками «Записать / Исправить» или редактор.
    message_id — отредактировать это сообщение; иначе отправить новое внизу чата,
    а у прошлого черновика убрать кнопки, чтобы их не нажали по ошибке."""
    state.set_state(user_id, stage="editing" if editing else "waiting_confirmation")
    st = state.get_state(user_id)

    text = draft_text(st, editing)
    keyboard = draft_keyboard(st, editing)

    if message_id is None:
        remove_keyboard(chat_id, st.get("draft_message_id"))
        message_id = bot.send_message(chat_id, text, reply_markup=keyboard).message_id
    else:
        edit(chat_id, message_id, text, keyboard)

    state.set_state(user_id, draft_message_id=message_id)


def update_draft_items(user_id, items):
    state.set_state(user_id, result=nutrition.make_result(items))


def save_draft(call, user_id, st):
    result = st["result"]

    if not result["items"]:
        answer(call, "Список пуст — добавь продукт или отмени")
        return

    description = formatting.build_description(result)
    meal_id = st.get("editing_meal_id")
    day_offset = st.get("day_offset", 0)

    if meal_id:
        if db.update_meal(meal_id, user_id, description, result):
            header = "✅ Запись обновлена!"
        else:
            header = "Запись не найдена — возможно, её уже удалили."
    else:
        db.add_meal(
            user_id,
            description,
            result["total_kcal"],
            protein=result["total_protein"],
            fat=result["total_fat"],
            carbs=result["total_carbs"],
            meal_type=st.get("explicit_meal_type"),
            items=result["items"],
            day_offset=day_offset,
        )
        if day_offset:
            header = f"✅ Записано на {formatting.format_day_offset(day_offset)}!"
        else:
            header = "✅ Записано!"

    state.clear_state(user_id)
    edit(
        call.message.chat.id,
        call.message.message_id,
        f"{header}\n\n{today_short_summary(user_id)}",
    )


def estimate_portion(call, user_id, st):
    """Кнопка «Оцени сам»: просим LLM оценить порции и показываем результат."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    edit(chat_id, message_id, "🤖 Считаю...")

    try:
        result = claude_client.analyze_food(st.get("food_text"))
    except claude_client.LLMUnavailableError:
        # Возвращаем кнопки, чтобы можно было нажать ещё раз
        edit(
            chat_id,
            message_id,
            LLM_UNAVAILABLE_TEXT,
            keyboards.portion_choice_keyboard(),
        )
        return

    if result is None:
        state.clear_state(user_id)
        edit(chat_id, message_id, NOT_FOOD_TEXT)
        return

    state.set_state(user_id, result=result, source="estimate")
    show_draft(chat_id, user_id, editing=False, message_id=message_id)


def handle_draft_callback(call, user_id, st, data):
    """Кнопки черновика: выбор порции, записать / исправить / отмена, редактор."""
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    if data == "portion_grams":
        state.set_state(user_id, stage="waiting_grams")
        edit(
            chat_id,
            message_id,
            "Напиши вес каждого продукта в граммах, например:\n"
            "рис 180 г, курица 200 г, овощи 100 г",
        )

    elif data == "portion_estimate":
        estimate_portion(call, user_id, st)

    elif data == "confirm_save":
        save_draft(call, user_id, st)

    elif data == "confirm_edit" or data == "edit_back":
        show_draft(chat_id, user_id, editing=True, message_id=message_id)

    elif data == "confirm_cancel":
        state.clear_state(user_id)
        edit(chat_id, message_id, "❌ Отменено")

    elif data == "edit_add":
        state.set_state(user_id, stage="waiting_new_item")
        edit(
            chat_id,
            message_id,
            "Что добавить? Например: соус 30 г",
            keyboards.editor_back_keyboard(),
        )

    elif data.startswith("edit_"):
        # edit_item_2, edit_grams_2, edit_remove_2 — действие с продуктом №2
        _, action, index_str = data.split("_")
        index = int(index_str)
        items = st["result"]["items"]

        if index >= len(items):  # список успел измениться
            show_draft(chat_id, user_id, editing=True, message_id=message_id)
            return

        item = items[index]

        if action == "item":
            edit(
                chat_id,
                message_id,
                f"Что сделать с этим продуктом?\n\n{formatting.format_item_line(item)}",
                keyboards.item_actions_keyboard(index),
            )

        elif action == "grams":
            state.set_state(user_id, stage="waiting_item_grams", edit_index=index)
            edit(
                chat_id,
                message_id,
                f"Сколько граммов «{item['name']}»? Сейчас {item['grams']} г.\n"
                "Напиши число, например: 200",
                keyboards.editor_back_keyboard(),
            )

        elif action == "remove":
            update_draft_items(user_id, items[:index] + items[index + 1 :])
            show_draft(chat_id, user_id, editing=True, message_id=message_id)


def handle_editor_text(message, user_id, st, stage, text):
    """Текст, присланный в режиме редактора. True — если сообщение обработано здесь."""
    if stage not in ("waiting_item_grams", "waiting_new_item", "editing"):
        return False

    items = st["result"]["items"]

    if stage == "waiting_item_grams":
        grams = parse_number(text, 1, 5000)
        index = st.get("edit_index", 0)

        if grams is None:
            bot.reply_to(message, "Напиши вес числом в граммах, например: 200")
            return True

        if index < len(items):
            items[index] = nutrition.scale_item(items[index], round(grams))
            update_draft_items(user_id, items)

        show_draft(message.chat.id, user_id, editing=True)
        return True

    bot.send_chat_action(message.chat.id, "typing")

    try:
        if stage == "waiting_new_item":
            new_result = claude_client.analyze_food(text)
        else:
            # Исправление словами: «рыбы было 200 г, хлеба не было»
            new_result = claude_client.correct_result(st["result"], text)
    except claude_client.LLMUnavailableError:
        bot.reply_to(message, LLM_UNAVAILABLE_TEXT)
        return True

    if new_result is None:
        bot.reply_to(message, "Не понял 🤔 Попробуй написать иначе.")
        return True

    if stage == "waiting_new_item":
        update_draft_items(user_id, items + new_result["items"])
    else:
        state.set_state(user_id, result=new_result)

    show_draft(message.chat.id, user_id, editing=True)
    return True


def start_new_food(message, user_id, text):
    """Новое описание еды: спрашиваем, как считать порцию."""
    # Прошлый незаконченный черновик больше не актуален — убираем его кнопки
    remove_keyboard(message.chat.id, state.get_state(user_id).get("draft_message_id"))
    state.clear_state(user_id)

    day_offset = db.detect_day_offset(text)
    question = "Как считаем порцию?"
    if day_offset:
        question += f"\n📅 Запишу на {formatting.format_day_offset(day_offset)}"

    sent = bot.reply_to(
        message, question, reply_markup=keyboards.portion_choice_keyboard()
    )

    state.set_state(
        user_id,
        stage="waiting_portion_choice",
        food_text=text,
        explicit_meal_type=db.detect_explicit_meal_type(text),
        day_offset=day_offset,
        draft_message_id=sent.message_id,
    )


# =========================
# ИСТОРИЯ И ПОВТОР
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
        edit(chat_id, message_id, text, keyboard)
    else:
        bot.send_message(chat_id, text, reply_markup=keyboard)


def show_meal_detail(call, user_id, meal_id, header=""):
    """Карточка записи из истории. Если запись уже удалена — возвращаемся к списку."""
    meal = db.get_meal_by_id(meal_id, user_id)

    if meal is None:
        answer(call, "Запись не найдена (возможно, уже удалена)")
        show_history_list(call.message.chat.id, user_id, call.message.message_id)
        return

    items = db.get_meal_items(meal_id, user_id)

    edit(
        call.message.chat.id,
        call.message.message_id,
        header + formatting.format_meal_detail(meal, items),
        keyboards.history_item_keyboard(meal_id, has_items=bool(items)),
    )


def start_history_edit(call, user_id, meal_id):
    """«Изменить состав» у записи из истории — открываем тот же редактор."""
    items = db.get_meal_items(meal_id, user_id)

    if not items:
        answer(call, "У этой записи нет состава (старая или ручная запись)")
        return

    remove_keyboard(call.message.chat.id, state.get_state(user_id).get("draft_message_id"))
    state.clear_state(user_id)
    state.set_state(
        user_id,
        result=nutrition.make_result(items),
        editing_meal_id=meal_id,
        draft_message_id=call.message.message_id,
    )
    show_draft(
        call.message.chat.id,
        user_id,
        editing=True,
        message_id=call.message.message_id,
    )


def show_repeat_list(chat_id, user_id):
    meals = db.get_frequent_meals(user_id)

    if not meals:
        bot.send_message(chat_id, "Пока нечего повторять — сначала запиши что-нибудь 🙂")
        return

    bot.send_message(
        chat_id,
        "🔁 Что записать ещё раз? (частые приёмы пищи)",
        reply_markup=keyboards.repeat_list_keyboard(meals),
    )


def repeat_meal(call, user_id, meal_id):
    new_id = db.copy_meal_to_today(meal_id, user_id)

    if new_id is None:
        answer(call, "Запись не найдена (возможно, уже удалена)")
        return

    _, _, _, description, calories, meal_type = db.get_meal_by_id(new_id, user_id)

    edit(
        call.message.chat.id,
        call.message.message_id,
        f"🔁 Записал ещё раз ({meal_type}):\n{description} — {calories} ккал\n\n"
        f"{today_short_summary(user_id)}",
        keyboards.undo_keyboard(new_id),
    )


# =========================
# ВЕС, ОТЧЁТЫ, НАСТРОЙКИ — вспомогательные
# =========================


def weight_trend_text(user_id):
    """'За неделю: −0.4 кг · за месяц: −1.8 кг' или пустая строка."""
    last = db.get_last_weight(user_id)

    if last is None:
        return ""

    parts = []
    for days, label in ((7, "за неделю"), (30, "за месяц")):
        date = (clock.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        past = db.get_last_weight(user_id, on_or_before=date)

        if past is not None and past[0] < last[0]:
            parts.append(f"{label}: {formatting.format_weight_change(last[1] - past[1])}")

    return " · ".join(parts).capitalize()


def ask_weight(chat_id, user_id):
    state.clear_state(user_id)
    state.set_state(user_id, stage="waiting_weight")

    last = db.get_last_weight(user_id)

    if last is None:
        bot.send_message(chat_id, "Напиши свой текущий вес числом, например: 78.4")
        return

    lines = [
        f"⚖️ Последний вес: {last[1]:g} кг "
        f"({formatting.format_date_ddmmyyyy(last[0])})"
    ]

    trend = weight_trend_text(user_id)
    if trend:
        lines.append(trend)

    lines.append("\nНапиши текущий вес числом, например: 78.4")

    bot.send_message(chat_id, "\n".join(lines), reply_markup=keyboards.weight_keyboard())


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
# КОМАНДЫ
# =========================


@bot.message_handler(commands=["start"])
def start(message):
    ensure_registered(message.from_user.id, message.chat.id)
    bot.reply_to(
        message,
        "Привет 👋\n\n"
        "Опиши, что ты съел, обычными словами — или пришли фото тарелки 📷. "
        "Я разложу еду на продукты и посчитаю калории и БЖУ.\n\n"
        "• Можно указать приём пищи: «на завтрак 3 яйца»\n"
        "• Можно записать задним числом: «вчера на ужин пицца»\n"
        "• Можно просто число калорий: 450\n\n"
        "Кнопки внизу — итог дня, история, повтор частых блюд, вес, отчёты и настройки.",
        reply_markup=keyboards.main_menu_keyboard(),
    )


@bot.message_handler(commands=["today"])
def today(message):
    ensure_registered(message.from_user.id, message.chat.id)
    user_id = message.from_user.id

    bot.reply_to(
        message,
        formatting.format_today_text(
            db.get_today_meals(user_id),
            db.get_today_totals(user_id),
            db.get_daily_goal(user_id),
            db.get_protein_goal(user_id),
        ),
    )


@bot.message_handler(commands=["history"])
def history_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    show_history_list(message.chat.id, message.from_user.id)


@bot.message_handler(commands=["repeat"])
def repeat_command(message):
    ensure_registered(message.from_user.id, message.chat.id)
    show_repeat_list(message.chat.id, message.from_user.id)


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
# ФОТО ЕДЫ
# =========================


@bot.message_handler(content_types=["photo"])
def photo_message(message):
    user_id = message.from_user.id
    ensure_registered(user_id, message.chat.id)
    caption = (message.caption or "").strip()

    progress = bot.reply_to(message, "📷 Смотрю на фото...")

    # Telegram хранит несколько размеров фото, последний — самый большой
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        image_bytes = bot.download_file(file_info.file_path)
    except Exception:  # ошибка Telegram или сети
        logger.exception("Не удалось скачать фото")
        edit(message.chat.id, progress.message_id, "Не получилось загрузить фото 😔")
        return

    try:
        result = claude_client.analyze_food(caption, image_bytes=image_bytes)
    except claude_client.LLMUnavailableError:
        edit(message.chat.id, progress.message_id, LLM_UNAVAILABLE_TEXT)
        return

    if result is None:
        edit(
            message.chat.id,
            progress.message_id,
            "Не вижу на фото еды 🤔 Попробуй другой ракурс или опиши словами.",
        )
        return

    remove_keyboard(message.chat.id, state.get_state(user_id).get("draft_message_id"))
    state.clear_state(user_id)
    state.set_state(
        user_id,
        result=result,
        source="photo",
        explicit_meal_type=db.detect_explicit_meal_type(caption),
        day_offset=db.detect_day_offset(caption),
        draft_message_id=progress.message_id,
    )
    show_draft(message.chat.id, user_id, editing=False, message_id=progress.message_id)


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

    if text == "🔁 Повторить":
        show_repeat_list(message.chat.id, user_id)
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

    # --- Редактор черновика: вес продукта, новый продукт, исправление словами ---
    if handle_editor_text(message, user_id, current_state, stage, text):
        return

    # --- Прислал граммы после "Я укажу граммы" ---
    if stage == "waiting_grams":
        bot.send_chat_action(message.chat.id, "typing")

        try:
            result = claude_client.analyze_food(
                current_state.get("food_text"), grams_text=text
            )
        except claude_client.LLMUnavailableError:
            # состояние не сбрасываем — можно просто прислать граммы ещё раз
            bot.reply_to(message, LLM_UNAVAILABLE_TEXT)
            return

        if result is None:
            bot.reply_to(
                message, "Не получилось посчитать 🤔 Попробуй написать граммы ещё раз."
            )
            return

        state.set_state(user_id, result=result, source="grams")
        show_draft(message.chat.id, user_id, editing=False)
        return

    # --- Ввод веса ---
    if stage == "waiting_weight":
        weight = parse_number(text, 20, 400)

        if weight is None:
            bot.reply_to(
                message, "Не получилось распознать вес. Напиши число в кг, например: 78.4"
            )
            return

        previous = db.get_last_weight(user_id)
        db.add_weight(user_id, weight)
        state.clear_state(user_id)

        reply = f"⚖️ Записал: {weight:g} кг"
        if previous is not None and previous[0] != clock.today_str():
            change = formatting.format_weight_change(weight - previous[1])
            reply += f" ({change} с прошлого раза)"

        bot.reply_to(message, reply)
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

        if start_date > end_date:
            bot.reply_to(message, "Начало периода должно быть раньше конца 🙂")
            return

        if (end_date - start_date).days > 366:
            bot.reply_to(message, "Период слишком длинный — максимум год.")
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
            # 21:00 и 21.00 — оба варианта годятся
            hour_str, minute_str = text.replace(".", ":").split(":")
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
        goal = parse_number(text, 800, 6000)

        if goal is None:
            bot.reply_to(
                message, "Напиши цель числом от 800 до 6000 ккал, например: 2200"
            )
            return

        goal = round(goal)
        db.set_daily_goal(user_id, goal)
        state.clear_state(user_id)

        bot.reply_to(message, f"🎯 Готово! Дневная цель: {goal} ккал.")
        return

    # --- Цель по белку ---
    if stage == "waiting_protein_goal":
        protein_goal = parse_number(text, 0, 400)

        if protein_goal is None:
            bot.reply_to(message, "Напиши число граммов, например: 120 (или 0)")
            return

        protein_goal = round(protein_goal) or None  # 0 — убрать цель
        db.set_protein_goal(user_id, protein_goal)
        state.clear_state(user_id)

        if protein_goal:
            bot.reply_to(message, f"🥩 Готово! Цель по белку: {protein_goal} г в день.")
        else:
            bot.reply_to(message, "🥩 Цель по белку убрана.")
        return

    # --- Форма расчёта цели: вес ---
    if stage == "waiting_goal_weight":
        weight = parse_number(text, 20, 400)

        if weight is None:
            bot.reply_to(message, "Напиши вес числом в кг, например: 78.5")
            return

        state.set_state(user_id, stage="waiting_goal_height", goal_weight=weight)
        bot.reply_to(message, "Какой у тебя рост в см?")
        return

    # --- Форма расчёта цели: рост ---
    if stage == "waiting_goal_height":
        height = parse_number(text, 100, 250)

        if height is None:
            bot.reply_to(message, "Напиши рост числом в см, например: 175")
            return

        state.set_state(user_id, stage="waiting_goal_age", goal_height=height)
        bot.reply_to(message, "Сколько тебе лет?")
        return

    # --- Форма расчёта цели: возраст (дальше — кнопки) ---
    if stage == "waiting_goal_age":
        age = parse_number(text, 10, 100)

        if age is None:
            bot.reply_to(message, "Напиши возраст числом, например: 27")
            return

        state.set_state(
            user_id, stage="waiting_goal_gender_button", goal_age=round(age)
        )
        bot.reply_to(message, "Какой пол?", reply_markup=keyboards.gender_keyboard())
        return

    # --- Обычное число калорий ---
    # isdecimal, а не isdigit: isdigit пропускает «²», на котором int() падает
    if text.isdecimal():
        calories = int(text)

        if not (1 <= calories <= 5000):
            bot.reply_to(
                message,
                "Похоже на опечатку 🤔 За один раз можно записать от 1 до 5000 ккал.",
            )
            return

        db.add_meal(user_id, db.MANUAL_DESCRIPTION, calories)
        state.clear_state(user_id)

        bot.reply_to(
            message, f"✅ Записал {calories} ккал\n\n{today_short_summary(user_id)}"
        )
        return

    # --- Новое описание еды ---
    start_new_food(message, user_id, text)


# =========================
# НАЖАТИЯ НА КНОПКИ
# =========================


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    message_id = call.message.message_id
    ensure_registered(user_id, chat_id)
    current_state = state.get_state(user_id)
    data = call.data

    # --- Черновик приёма пищи ---
    if data.startswith(DRAFT_CALLBACK_PREFIXES):
        if message_id != current_state.get("draft_message_id"):
            # Кнопка от старого черновика: есть более новый или этот уже записан
            answer(call, "Этот черновик устарел — напиши еду заново")
            remove_keyboard(chat_id, message_id)
            return

        handle_draft_callback(call, user_id, current_state, data)

    # --- История ---

    elif data == "histlist":
        show_history_list(chat_id, user_id, message_id)

    elif data.startswith(("histopen_", "histback_")):
        show_meal_detail(call, user_id, int(data.split("_")[1]))

    elif data.startswith("histedit_"):
        start_history_edit(call, user_id, int(data.split("_")[1]))

    elif data.startswith("histtype_"):
        meal_id = int(data.split("_")[1])
        edit(
            chat_id,
            message_id,
            "Выбери правильный приём пищи:",
            keyboards.meal_type_choice_keyboard(meal_id),
        )

    elif data.startswith("settype_"):
        _, meal_id_str, code = data.split("_")
        meal_id = int(meal_id_str)
        new_type = db.MEAL_TYPE_CODES.get(code)

        if new_type is not None:
            db.update_meal_type(meal_id, user_id, new_type)

        show_meal_detail(call, user_id, meal_id, header="✅ Обновлено!\n\n")

    elif data.startswith("histdel_"):
        meal_id = int(data.split("_")[1])
        meal = db.get_meal_by_id(meal_id, user_id)

        if meal is None:
            answer(call, "Запись не найдена (возможно, уже удалена)")
            show_history_list(chat_id, user_id, message_id)
            return

        edit(
            chat_id,
            message_id,
            "Удалить эту запись?\n\n" + formatting.format_meal_detail(meal),
            keyboards.delete_confirm_keyboard(meal_id),
        )

    elif data.startswith("histdelok_"):
        db.delete_meal(int(data.split("_")[1]), user_id)
        answer(call, "Удалено")
        show_history_list(chat_id, user_id, message_id)

    # --- Повтор ---

    elif data.startswith("repeat_"):
        repeat_meal(call, user_id, int(data.split("_")[1]))

    elif data.startswith("undo_"):
        db.delete_meal(int(data.split("_")[1]), user_id)
        edit(
            chat_id,
            message_id,
            f"↩️ Отменил повтор.\n\n{today_short_summary(user_id)}",
        )

    # --- Вес ---

    elif data == "weight_chart":
        image = reports.build_weight_image(user_id)

        if image is None:
            answer(call, "Для графика нужно хотя бы 2 записи веса")
            return

        bot.send_photo(chat_id, image)

    # --- Отчёты ---

    elif data in ("reportperiod_week", "reportperiod_month"):
        days = 6 if data == "reportperiod_week" else 29
        today_date = clock.now().date()
        start = today_date - timedelta(days=days)

        state.clear_state(user_id)
        state.set_state(
            user_id,
            stage="waiting_report_format",
            report_start=start.isoformat(),
            report_end=today_date.isoformat(),
        )
        edit(
            chat_id,
            message_id,
            "Какой формат отчёта?",
            keyboards.report_format_keyboard(),
        )

    elif data == "reportperiod_custom":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_custom_period")
        edit(
            chat_id,
            message_id,
            "Напиши период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ\nНапример: 01.09.2026-14.09.2026",
        )

    elif data.startswith("reportformat_") and not current_state.get("report_start"):
        # Период потерялся (например, отчёт уже построен по этой кнопке)
        edit(chat_id, message_id, "Я забыл выбранный период 🤷 Открой 📈 Отчёт ещё раз.")

    elif data == "reportformat_text":
        start = current_state.get("report_start")
        end = current_state.get("report_end")

        report_text = reports.build_text_report(user_id, start, end)
        state.clear_state(user_id)

        edit(chat_id, message_id, report_text)

    elif data == "reportformat_image":
        start = current_state.get("report_start")
        end = current_state.get("report_end")

        edit(chat_id, message_id, "📈 Строю график...")

        image = reports.build_image_report(user_id, start, end)
        state.clear_state(user_id)

        if image is None:
            bot.send_message(
                chat_id,
                "За этот период записей нет — картинку строить не из чего.",
            )
        else:
            bot.send_photo(chat_id, image)

    # --- Настройки ---

    elif data == "settings_reminder":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_reminder_time")

        current_hour, current_minute = db.get_reminder_time(user_id)
        edit(
            chat_id,
            message_id,
            f"Сейчас напоминание приходит в {current_hour:02d}:{current_minute:02d}.\n"
            "Напиши новое время в формате ЧЧ:ММ, например 21:00",
        )

    elif data == "settings_goal":
        current_goal = db.get_daily_goal(user_id)
        edit(
            chat_id,
            message_id,
            f"Сейчас дневная цель: {current_goal} ккал.\nКак хочешь её задать?",
            keyboards.goal_mode_keyboard(),
        )

    elif data == "settings_protein":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_protein_goal")

        protein_goal = db.get_protein_goal(user_id)
        current = f"{protein_goal} г" if protein_goal else "не задана"
        edit(
            chat_id,
            message_id,
            f"Сейчас цель по белку: {current}.\n"
            "Напиши, сколько граммов белка в день хочешь есть (например, 120), "
            "или 0 — чтобы убрать цель.\n\n"
            "Подсказка: обычно это 1.4–1.8 г на кг веса.",
        )

    elif data == "settings_back":
        edit(chat_id, message_id, "⚙️ Настройки:", keyboards.settings_menu_keyboard())

    elif data == "goalmode_manual":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_manual_goal")
        edit(
            chat_id,
            message_id,
            "Напиши свою дневную цель числом (в ккал), например: 2200",
        )

    elif data == "goalmode_calc":
        state.clear_state(user_id)
        state.set_state(user_id, stage="waiting_goal_weight")
        edit(
            chat_id,
            message_id,
            "Небольшая форма, чтобы рассчитать цель под тебя.\n\nКакой у тебя вес в кг?",
        )

    elif data.startswith("gender_"):
        gender = data.split("_")[1]  # male / female
        state.set_state(user_id, goal_gender=gender)

        edit(
            chat_id,
            message_id,
            "Какой у тебя уровень активности?",
            keyboards.activity_keyboard(),
        )

    elif data.startswith("activity_"):
        activity = data[len("activity_") :]  # low / medium / high / very_high
        state.set_state(user_id, goal_activity=activity)

        edit(
            chat_id,
            message_id,
            "И последнее — какая у тебя цель?",
            keyboards.goal_type_keyboard(),
        )

    elif data.startswith("goaltype_"):
        goal_type = data[len("goaltype_") :]  # lose / maintain / gain

        weight = current_state.get("goal_weight")
        height = current_state.get("goal_height")
        age = current_state.get("goal_age")
        gender = current_state.get("goal_gender")
        activity = current_state.get("goal_activity")

        if None in (weight, height, age, gender, activity):
            answer(call, "Что-то потерялось, начни заново через Настройки")
            state.clear_state(user_id)
            return

        goal = calc.calculate_daily_goal(
            weight, height, age, gender, activity, goal_type
        )
        protein_goal = calc.calculate_protein_goal(weight, goal_type)

        db.set_daily_goal(user_id, goal)
        db.set_protein_goal(user_id, protein_goal)
        state.clear_state(user_id)

        edit(
            chat_id,
            message_id,
            f"🎯 Готово! Рассчитанная дневная цель: {goal} ккал.\n"
            f"🥩 Цель по белку: {protein_goal} г.\n\n"
            "Если захочешь поменять — снова зайди в ⚙️ Настройки.",
        )

    answer(call)


# =========================
# ЗАПУСК
# =========================


def main():
    setup_logging()

    bot.set_my_commands(
        [
            telebot.types.BotCommand("start", "Начать"),
            telebot.types.BotCommand("today", "Сегодня"),
            telebot.types.BotCommand("history", "История записей"),
            telebot.types.BotCommand("repeat", "Повторить приём пищи"),
            telebot.types.BotCommand("weight", "Записать вес"),
            telebot.types.BotCommand("report", "Отчёт за период"),
            telebot.types.BotCommand("settings", "Настройки"),
        ]
    )

    reminders.start_reminders(bot)

    logger.info("Бот запущен! Часовой пояс: %s", clock.TIMEZONE)

    bot.infinity_polling(skip_pending=True)


# Запуск только при `python bot.py`; при импорте (например, из тестов) бот не стартует
if __name__ == "__main__":
    main()
