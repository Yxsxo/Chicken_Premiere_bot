"""Общие настройки тестов: временная база, заглушки Telegram и LLM.

pytest сам находит этот файл и выполняет его раньше тестов.
Фикстуры (функции с @pytest.fixture) тесты получают по имени аргумента:
def test_x(chat, llm) — и pytest передаст готовые chat и llm.
"""

import copy
import os
import tempfile
from types import SimpleNamespace as NS

# ВАЖНО: до импорта модулей бота — своя пустая база и ненастоящие ключи.
# load_dotenv не перезаписывает уже заданные переменные, так что .env тесты не трогают.
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["BOT_TOKEN"] = "123:test-token"
os.environ["ANTHROPIC_API_KEY"] = "test-key"
os.environ["BOT_TIMEZONE"] = "Europe/Moscow"

import pytest

import bot as bot_module
import claude_client
import db
import nutrition

USER_ID = 42

TABLES = ["meals", "meal_items", "weights", "known_users", "user_states"]


@pytest.fixture(autouse=True)
def clean_db():
    """Перед каждым тестом база пустая — тесты не влияют друг на друга."""
    for table in TABLES:
        db.cursor.execute(f"DELETE FROM {table}")
    db.connection.commit()


def item(name, grams, kcal, protein=0, fat=0, carbs=0, quantity=None):
    """Продукт в том виде, в каком его возвращает разбор LLM."""
    return {
        "name": name,
        "quantity": quantity or f"{grams} г",
        "grams": grams,
        "kcal": kcal,
        "protein": protein,
        "fat": fat,
        "carbs": carbs,
    }


# =========================
# ЗАГЛУШКА LLM
# =========================


class FakeLLM:
    """Вместо запроса к Claude возвращает заранее заданный ответ."""

    def __init__(self):
        self.requests = []
        self.result = None
        self.unavailable = False

    def answer(self, *items):
        self.result = nutrition.make_result(list(items))

    def __call__(self, content):
        self.requests.append(content)

        if self.unavailable:
            raise claude_client.LLMUnavailableError("тестовая ошибка")

        return copy.deepcopy(self.result)


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM()
    # monkeypatch подменяет функцию только на время теста
    monkeypatch.setattr(claude_client, "_ask", fake)
    return fake


# =========================
# ЗАГЛУШКА TELEGRAM
# =========================


def _buttons(markup):
    """Кнопки инлайн-клавиатуры списком (текст, callback_data)."""
    if markup is None or not hasattr(markup, "keyboard"):
        return []

    return [
        (button.text, button.callback_data)
        for row in markup.keyboard
        for button in row
        if hasattr(button, "callback_data")
    ]


class FakeTelegram:
    """Вместо Telegram: запоминает сообщения бота, их текст и кнопки."""

    def __init__(self):
        self.messages = {}  # message_id -> {"text": ..., "buttons": [...]}
        self.order = []  # message_id в порядке последнего изменения
        self.toasts = []  # всплывающие ответы на кнопки
        self.photos = []  # отправленные картинки (байты)
        self._next_id = 100

    def _store(self, message_id, text, markup):
        self.messages[message_id] = {"text": text, "buttons": _buttons(markup)}
        if message_id in self.order:
            self.order.remove(message_id)
        self.order.append(message_id)

    def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self._next_id += 1
        self._store(self._next_id, text, reply_markup)
        return NS(message_id=self._next_id, chat=NS(id=chat_id))

    def reply_to(self, message, text, reply_markup=None, **kwargs):
        return self.send_message(message.chat.id, text, reply_markup)

    def edit_message_text(self, text, chat_id, message_id, reply_markup=None, **kwargs):
        self._store(message_id, text, reply_markup)

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kwargs):
        if message_id in self.messages:
            self.messages[message_id]["buttons"] = _buttons(reply_markup)

    def answer_callback_query(self, callback_id, text=None, **kwargs):
        if text:
            self.toasts.append(text)

    def send_photo(self, chat_id, photo, **kwargs):
        self.photos.append(photo.getvalue())

    def send_chat_action(self, *args, **kwargs):
        pass

    def get_file(self, file_id):
        return NS(file_path="photo.jpg")

    def download_file(self, file_path):
        return b"\xff\xd8 fake jpeg"


class Chat:
    """Переписка с ботом от лица пользователя: пишем, жмём кнопки, читаем ответы."""

    def __init__(self, telegram):
        self.tg = telegram

    def _message(self, **fields):
        return NS(from_user=NS(id=USER_ID), chat=NS(id=USER_ID), message_id=1, **fields)

    def send(self, text):
        bot_module.text_message(self._message(text=text))

    def send_photo(self, caption=None):
        bot_module.photo_message(
            self._message(caption=caption, photo=[NS(file_id="small"), NS(file_id="big")])
        )

    def click(self, callback_data, message_id=None):
        """Нажать кнопку. Без message_id ищем самое свежее сообщение с такой кнопкой."""
        if message_id is None:
            message_id = self._find_button(callback_data)

        bot_module.handle_callback(
            NS(
                id="callback",
                from_user=NS(id=USER_ID),
                data=callback_data,
                message=NS(chat=NS(id=USER_ID), message_id=message_id),
            )
        )

    def _find_button(self, callback_data):
        for message_id in reversed(self.tg.order):
            if any(data == callback_data for _, data in self.tg.messages[message_id]["buttons"]):
                return message_id
        raise AssertionError(f"Нет кнопки {callback_data!r} ни в одном сообщении")

    @property
    def last_id(self):
        return self.tg.order[-1]

    @property
    def last_text(self):
        return self.tg.messages[self.last_id]["text"]

    @property
    def last_buttons(self):
        return [text for text, _ in self.tg.messages[self.last_id]["buttons"]]


@pytest.fixture
def telegram(monkeypatch):
    fake = FakeTelegram()
    for name in (
        "send_message",
        "reply_to",
        "edit_message_text",
        "edit_message_reply_markup",
        "answer_callback_query",
        "send_photo",
        "send_chat_action",
        "get_file",
        "download_file",
    ):
        monkeypatch.setattr(bot_module.bot, name, getattr(fake, name))
    return fake


@pytest.fixture
def chat(telegram):
    return Chat(telegram)
