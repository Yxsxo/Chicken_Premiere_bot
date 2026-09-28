import json
import re
import sqlite3
import threading
from datetime import timedelta
from functools import wraps

import clock

# =========================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ
# =========================

DEFAULT_DAILY_GOAL = 2200
DEFAULT_REMINDER_HOUR = 21
DEFAULT_REMINDER_MINUTE = 0

MANUAL_DESCRIPTION = "Ручная запись"

# =========================
# ПОДКЛЮЧЕНИЕ К БАЗЕ
# =========================

connection = sqlite3.connect("calories.db", check_same_thread=False)
cursor = connection.cursor()

# Бот обрабатывает сообщения в нескольких потоках, плюс поток напоминаний.
# Курсор у всех общий, поэтому пускаем к базе строго по одному.
# RLock (а не Lock), чтобы одна функция базы могла вызвать другую.
_db_lock = threading.RLock()


def synchronized(func):
    """Декоратор: функция работает с базой, только взяв _db_lock."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        with _db_lock:
            return func(*args, **kwargs)

    return wrapper


# =========================
# СОЗДАНИЕ ТАБЛИЦ (если их ещё нет)
# =========================

cursor.execute("""
CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    calories INTEGER,
    date TEXT
)
""")

# Состав приёма пищи: каждый продукт отдельной строкой
cursor.execute("""
CREATE TABLE IF NOT EXISTS meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER,
    name TEXT,
    quantity TEXT,
    grams INTEGER,
    kcal INTEGER,
    protein REAL,
    fat REAL,
    carbs REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    date TEXT,
    weight REAL
)
""")

cursor.execute(f"""
CREATE TABLE IF NOT EXISTS known_users (
    user_id INTEGER PRIMARY KEY,
    chat_id INTEGER,
    daily_goal INTEGER DEFAULT {DEFAULT_DAILY_GOAL},
    reminder_hour INTEGER DEFAULT {DEFAULT_REMINDER_HOUR},
    reminder_minute INTEGER DEFAULT {DEFAULT_REMINDER_MINUTE}
)
""")

# Состояние диалога (на каком шаге пользователь) — в JSON.
# Хранится в базе, чтобы не теряться при перезапуске бота.
cursor.execute("""
CREATE TABLE IF NOT EXISTS user_states (
    user_id INTEGER PRIMARY KEY,
    data TEXT
)
""")

connection.commit()

# =========================
# ОБНОВЛЕНИЕ СТАРЫХ ТАБЛИЦ (без потери данных)
# =========================

cursor.execute("PRAGMA table_info(meals)")
existing_meal_columns = [column[1] for column in cursor.fetchall()]

meal_columns_to_add = {
    "description": "TEXT",
    "time": "TEXT",
    "protein": "REAL",
    "fat": "REAL",
    "carbs": "REAL",
    "meal_type": "TEXT",
}

for column_name, column_type in meal_columns_to_add.items():
    if column_name not in existing_meal_columns:
        cursor.execute(f"ALTER TABLE meals ADD COLUMN {column_name} {column_type}")

cursor.execute("PRAGMA table_info(known_users)")
existing_user_columns = [column[1] for column in cursor.fetchall()]

user_columns_to_add = {
    "daily_goal": f"INTEGER DEFAULT {DEFAULT_DAILY_GOAL}",
    "reminder_hour": f"INTEGER DEFAULT {DEFAULT_REMINDER_HOUR}",
    "reminder_minute": f"INTEGER DEFAULT {DEFAULT_REMINDER_MINUTE}",
    "protein_goal": "INTEGER",  # NULL — цель по белку не задана
}

for column_name, column_def in user_columns_to_add.items():
    if column_name not in existing_user_columns:
        cursor.execute(f"ALTER TABLE known_users ADD COLUMN {column_name} {column_def}")

connection.commit()


# =========================
# ПРИЁМЫ ПИЩИ ПО ВРЕМЕНИ
# =========================

MEAL_TYPE_CODES = {
    "b": "завтрак",
    "l": "обед",
    "d": "ужин",
    "s": "перекус",
}


def determine_meal_type(time_str):
    hour, minute = map(int, time_str.split(":"))
    total_minutes = hour * 60 + minute

    if 6 * 60 <= total_minutes <= 12 * 60:
        return "завтрак"
    elif 12 * 60 + 1 <= total_minutes <= 18 * 60:
        return "обед"
    elif 18 * 60 + 1 <= total_minutes <= 23 * 60 + 59:
        return "ужин"
    else:
        return "перекус"


def detect_explicit_meal_type(text):
    lowered = text.lower()

    if "завтрак" in lowered:
        return "завтрак"
    elif "обед" in lowered:
        return "обед"
    elif "ужин" in lowered:
        return "ужин"
    elif "перекус" in lowered:
        return "перекус"

    return None


def detect_day_offset(text):
    """«вчера» → 1, «позавчера» → 2, иначе 0.
    \\b — граница слова: «вчерашний суп» не считается за «вчера»."""
    lowered = text.lower()

    if re.search(r"\bпозавчера\b", lowered):
        return 2
    if re.search(r"\bвчера\b", lowered):
        return 1

    return 0


# =========================
# СОСТОЯНИЕ ДИАЛОГА
# =========================


@synchronized
def load_state(user_id):
    cursor.execute("SELECT data FROM user_states WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return json.loads(row[0]) if row else {}


@synchronized
def update_state(user_id, changes):
    """Прочитать, дополнить и сохранить — под одной блокировкой,
    чтобы два одновременных обновления не затёрли друг друга."""
    data = load_state(user_id)
    data.update(changes)
    cursor.execute(
        """
        INSERT INTO user_states (user_id, data) VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET data = excluded.data
        """,
        (user_id, json.dumps(data, ensure_ascii=False)),
    )
    connection.commit()


@synchronized
def delete_state(user_id):
    cursor.execute("DELETE FROM user_states WHERE user_id = ?", (user_id,))
    connection.commit()


# =========================
# ПОЛЬЗОВАТЕЛИ И НАСТРОЙКИ
# =========================


@synchronized
def register_user(user_id, chat_id):
    cursor.execute(
        """
        INSERT INTO known_users (user_id, chat_id)
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id
        """,
        (user_id, chat_id),
    )
    connection.commit()


@synchronized
def get_all_known_users():
    cursor.execute(
        "SELECT user_id, chat_id, daily_goal, reminder_hour, reminder_minute FROM known_users"
    )
    return cursor.fetchall()


@synchronized
def get_daily_goal(user_id):
    cursor.execute("SELECT daily_goal FROM known_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else DEFAULT_DAILY_GOAL


@synchronized
def set_daily_goal(user_id, goal):
    cursor.execute(
        "UPDATE known_users SET daily_goal = ? WHERE user_id = ?",
        (goal, user_id),
    )
    connection.commit()


@synchronized
def get_protein_goal(user_id):
    cursor.execute("SELECT protein_goal FROM known_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else None


@synchronized
def set_protein_goal(user_id, goal):
    """goal=None — убрать цель по белку."""
    cursor.execute(
        "UPDATE known_users SET protein_goal = ? WHERE user_id = ?",
        (goal, user_id),
    )
    connection.commit()


@synchronized
def get_reminder_time(user_id):
    cursor.execute(
        "SELECT reminder_hour, reminder_minute FROM known_users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    return row if row else (DEFAULT_REMINDER_HOUR, DEFAULT_REMINDER_MINUTE)


@synchronized
def set_reminder_time(user_id, hour, minute):
    cursor.execute(
        "UPDATE known_users SET reminder_hour = ?, reminder_minute = ? WHERE user_id = ?",
        (hour, minute, user_id),
    )
    connection.commit()


# =========================
# ПРИЁМЫ ПИЩИ
# =========================


@synchronized
def get_today_calories(user_id):
    today = clock.today_str()

    cursor.execute(
        "SELECT SUM(calories) FROM meals WHERE user_id = ? AND date = ?",
        (user_id, today),
    )

    result = cursor.fetchone()[0]
    return result if result is not None else 0


@synchronized
def get_today_totals(user_id):
    """Калории и БЖУ за сегодня: (kcal, protein, fat, carbs)."""
    cursor.execute(
        """
        SELECT COALESCE(SUM(calories), 0), COALESCE(SUM(protein), 0),
               COALESCE(SUM(fat), 0), COALESCE(SUM(carbs), 0)
        FROM meals
        WHERE user_id = ? AND date = ?
        """,
        (user_id, clock.today_str()),
    )
    kcal, protein, fat, carbs = cursor.fetchone()
    return kcal, round(protein), round(fat), round(carbs)


def _insert_items(meal_id, items):
    for item in items:
        cursor.execute(
            """
            INSERT INTO meal_items (
                meal_id, name, quantity, grams, kcal, protein, fat, carbs
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meal_id,
                item["name"],
                item["quantity"],
                item["grams"],
                item["kcal"],
                item["protein"],
                item["fat"],
                item["carbs"],
            ),
        )


@synchronized
def add_meal(
    user_id,
    description,
    calories,
    protein=None,
    fat=None,
    carbs=None,
    meal_type=None,
    items=None,
    day_offset=0,
):
    """Сохраняет приём пищи и возвращает его id.
    day_offset=1 — запись на вчера (время тогда неизвестно, пишем пустое)."""
    now = clock.now()

    if day_offset:
        date = (now - timedelta(days=day_offset)).strftime("%Y-%m-%d")
        current_time = None
    else:
        date = now.strftime("%Y-%m-%d")
        current_time = now.strftime("%H:%M")

    if meal_type is None and current_time is not None:
        meal_type = determine_meal_type(current_time)

    cursor.execute(
        """
        INSERT INTO meals (
            user_id, calories, date, description,
            time, protein, fat, carbs, meal_type
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            calories,
            date,
            description,
            current_time,
            protein,
            fat,
            carbs,
            meal_type,
        ),
    )
    meal_id = cursor.lastrowid

    if items:
        _insert_items(meal_id, items)

    connection.commit()
    return meal_id


@synchronized
def update_meal(meal_id, user_id, description, result):
    """Перезаписывает состав и итоги уже сохранённого приёма пищи."""
    cursor.execute(
        """
        UPDATE meals
        SET description = ?, calories = ?, protein = ?, fat = ?, carbs = ?
        WHERE id = ? AND user_id = ?
        """,
        (
            description,
            result["total_kcal"],
            result["total_protein"],
            result["total_fat"],
            result["total_carbs"],
            meal_id,
            user_id,
        ),
    )

    if cursor.rowcount == 0:  # запись чужая или уже удалена
        return False

    cursor.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
    _insert_items(meal_id, result["items"])
    connection.commit()
    return True


@synchronized
def get_meal_items(meal_id, user_id):
    """Состав приёма пищи списком словарей (пустой — у старых и ручных записей)."""
    cursor.execute(
        """
        SELECT i.name, i.quantity, i.grams, i.kcal, i.protein, i.fat, i.carbs
        FROM meal_items i
        JOIN meals m ON m.id = i.meal_id
        WHERE i.meal_id = ? AND m.user_id = ?
        ORDER BY i.id
        """,
        (meal_id, user_id),
    )
    keys = ["name", "quantity", "grams", "kcal", "protein", "fat", "carbs"]
    return [dict(zip(keys, row)) for row in cursor.fetchall()]


@synchronized
def copy_meal_to_today(meal_id, user_id):
    """Повтор: копия приёма пищи на сегодня. Возвращает id новой записи или None."""
    cursor.execute(
        """
        SELECT description, calories, protein, fat, carbs
        FROM meals WHERE id = ? AND user_id = ?
        """,
        (meal_id, user_id),
    )
    row = cursor.fetchone()

    if row is None:
        return None

    description, calories, protein, fat, carbs = row
    items = get_meal_items(meal_id, user_id)

    return add_meal(
        user_id, description, calories, protein, fat, carbs, items=items
    )


@synchronized
def get_today_meals(user_id):
    today = clock.today_str()

    cursor.execute(
        """
        SELECT time, description, calories, meal_type
        FROM meals
        WHERE user_id = ? AND date = ?
        ORDER BY id
        """,
        (user_id, today),
    )
    return cursor.fetchall()


@synchronized
def get_last_meals(user_id, limit=15):
    cursor.execute(
        """
        SELECT id, date, time, description, calories, meal_type
        FROM meals
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return cursor.fetchall()


@synchronized
def get_frequent_meals(user_id, limit=8):
    """Частые приёмы пищи для «Повторить»: (id последнего такого, описание, ккал).
    В SQLite при MAX(id) остальные столбцы берутся из той же строки,
    поэтому calories — от самой свежей записи с этим описанием."""
    cursor.execute(
        """
        SELECT MAX(id), description, calories
        FROM meals
        WHERE user_id = ? AND description IS NOT NULL AND description != ?
        GROUP BY description
        ORDER BY COUNT(*) DESC, MAX(id) DESC
        LIMIT ?
        """,
        (user_id, MANUAL_DESCRIPTION, limit),
    )
    return cursor.fetchall()


@synchronized
def get_meal_by_id(meal_id, user_id):
    cursor.execute(
        """
        SELECT id, date, time, description, calories, meal_type
        FROM meals
        WHERE id = ? AND user_id = ?
        """,
        (meal_id, user_id),
    )
    return cursor.fetchone()


@synchronized
def delete_meal(meal_id, user_id):
    # Сначала состав (только если запись принадлежит этому пользователю), потом саму запись
    cursor.execute(
        """
        DELETE FROM meal_items
        WHERE meal_id IN (SELECT id FROM meals WHERE id = ? AND user_id = ?)
        """,
        (meal_id, user_id),
    )
    cursor.execute(
        "DELETE FROM meals WHERE id = ? AND user_id = ?",
        (meal_id, user_id),
    )
    connection.commit()


@synchronized
def update_meal_type(meal_id, user_id, new_type):
    cursor.execute(
        "UPDATE meals SET meal_type = ? WHERE id = ? AND user_id = ?",
        (new_type, meal_id, user_id),
    )
    connection.commit()


# =========================
# ВЕС
# =========================


@synchronized
def add_weight(user_id, weight):
    """Один вес на день: если сегодня уже взвешивался — перезаписываем."""
    today = clock.today_str()

    cursor.execute(
        "DELETE FROM weights WHERE user_id = ? AND date = ?", (user_id, today)
    )
    cursor.execute(
        "INSERT INTO weights (user_id, date, weight) VALUES (?, ?, ?)",
        (user_id, today, weight),
    )
    connection.commit()


@synchronized
def get_last_weight(user_id, on_or_before=None):
    """Последний вес (date, weight) — вообще или на дату не позже on_or_before."""
    cursor.execute(
        """
        SELECT date, weight FROM weights
        WHERE user_id = ? AND date <= ?
        ORDER BY date DESC, id DESC
        LIMIT 1
        """,
        (user_id, on_or_before or "9999-12-31"),
    )
    return cursor.fetchone()


@synchronized
def get_weights(user_id, start_date):
    cursor.execute(
        """
        SELECT date, weight FROM weights
        WHERE user_id = ? AND date >= ?
        ORDER BY date
        """,
        (user_id, start_date),
    )
    return cursor.fetchall()


# =========================
# ОТЧЁТЫ
# =========================


@synchronized
def get_calories_by_day(user_id, start_date, end_date):
    cursor.execute(
        """
        SELECT date, SUM(calories)
        FROM meals
        WHERE user_id = ? AND date BETWEEN ? AND ?
        GROUP BY date
        ORDER BY date
        """,
        (user_id, start_date, end_date),
    )
    return cursor.fetchall()
