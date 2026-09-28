import sqlite3
from datetime import datetime

# =========================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ
# =========================

DEFAULT_DAILY_GOAL = 2200
DEFAULT_REMINDER_HOUR = 21
DEFAULT_REMINDER_MINUTE = 0

# =========================
# ПОДКЛЮЧЕНИЕ К БАЗЕ
# =========================

connection = sqlite3.connect("calories.db", check_same_thread=False)
cursor = connection.cursor()

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


# =========================
# ПОЛЬЗОВАТЕЛИ И НАСТРОЙКИ
# =========================


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


def get_all_known_users():
    cursor.execute(
        "SELECT user_id, chat_id, daily_goal, reminder_hour, reminder_minute FROM known_users"
    )
    return cursor.fetchall()


def get_daily_goal(user_id):
    cursor.execute("SELECT daily_goal FROM known_users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    return row[0] if row else DEFAULT_DAILY_GOAL


def set_daily_goal(user_id, goal):
    cursor.execute(
        "UPDATE known_users SET daily_goal = ? WHERE user_id = ?",
        (goal, user_id),
    )
    connection.commit()


def get_reminder_time(user_id):
    cursor.execute(
        "SELECT reminder_hour, reminder_minute FROM known_users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    return row if row else (DEFAULT_REMINDER_HOUR, DEFAULT_REMINDER_MINUTE)


def set_reminder_time(user_id, hour, minute):
    cursor.execute(
        "UPDATE known_users SET reminder_hour = ?, reminder_minute = ? WHERE user_id = ?",
        (hour, minute, user_id),
    )
    connection.commit()


# =========================
# ПРИЁМЫ ПИЩИ
# =========================


def get_today_calories(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT SUM(calories) FROM meals WHERE user_id = ? AND date = ?",
        (user_id, today),
    )

    result = cursor.fetchone()[0]
    return result if result is not None else 0


def add_meal(
    user_id, description, calories, protein=None, fat=None, carbs=None, meal_type=None
):
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    if meal_type is None:
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
            today,
            description,
            current_time,
            protein,
            fat,
            carbs,
            meal_type,
        ),
    )
    connection.commit()


def get_today_meals(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

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


def delete_meal(meal_id, user_id):
    cursor.execute(
        "DELETE FROM meals WHERE id = ? AND user_id = ?",
        (meal_id, user_id),
    )
    connection.commit()


def update_meal_type(meal_id, user_id, new_type):
    cursor.execute(
        "UPDATE meals SET meal_type = ? WHERE id = ? AND user_id = ?",
        (new_type, meal_id, user_id),
    )
    connection.commit()


# =========================
# ВЕС
# =========================


def add_weight(user_id, weight):
    today = datetime.now().strftime("%Y-%m-%d")

    cursor.execute(
        "INSERT INTO weights (user_id, date, weight) VALUES (?, ?, ?)",
        (user_id, today, weight),
    )
    connection.commit()


# =========================
# ОТЧЁТЫ
# =========================


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
