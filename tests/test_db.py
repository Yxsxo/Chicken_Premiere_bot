import threading
from datetime import timedelta

import pytest

import clock
import db
import nutrition
import state
from conftest import USER_ID, item

OTHER_USER = 777


def add_breakfast(user_id=USER_ID, **kwargs):
    result = nutrition.make_result([item("рыба", 150, 180, 30, 6, 0), item("хлеб", 30, 80)])
    meal_id = db.add_meal(
        user_id,
        "рыба 150 г, хлеб 30 г",
        result["total_kcal"],
        protein=result["total_protein"],
        fat=result["total_fat"],
        carbs=result["total_carbs"],
        items=result["items"],
        **kwargs,
    )
    return meal_id, result


# =========================
# РАСПОЗНАВАНИЕ ТЕКСТА
# =========================


@pytest.mark.parametrize(
    "text, offset",
    [
        ("вчера на ужин пицца", 1),
        ("Вчера съел 20 пельменей", 1),
        ("позавчера был торт", 2),
        ("доел вчерашний суп", 0),  # «вчерашний» — это не «вчера»
        ("гречка с курицей", 0),
    ],
)
def test_detect_day_offset(text, offset):
    assert db.detect_day_offset(text) == offset


@pytest.mark.parametrize(
    "time, meal_type",
    [("08:00", "завтрак"), ("12:00", "завтрак"), ("12:01", "обед"), ("19:30", "ужин"), ("03:00", "перекус")],
)
def test_determine_meal_type(time, meal_type):
    assert db.determine_meal_type(time) == meal_type


# =========================
# ПРИЁМЫ ПИЩИ
# =========================


def test_add_meal_saves_items_and_totals():
    meal_id, _ = add_breakfast()

    assert [i["name"] for i in db.get_meal_items(meal_id, USER_ID)] == ["рыба", "хлеб"]
    assert db.get_today_totals(USER_ID) == (260, 30, 6, 0)


def test_add_meal_yesterday():
    meal_id, _ = add_breakfast(day_offset=1)
    _, date, time, _, _, meal_type = db.get_meal_by_id(meal_id, USER_ID)

    yesterday = (clock.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert date == yesterday
    assert time is None  # время вчерашней записи неизвестно
    assert meal_type is None
    assert db.get_today_totals(USER_ID)[0] == 0  # в «сегодня» не попала


def test_update_meal_replaces_items():
    meal_id, result = add_breakfast()
    new_result = nutrition.make_result([result["items"][0]])  # убрали хлеб

    assert db.update_meal(meal_id, USER_ID, "рыба 150 г", new_result)
    assert len(db.get_meal_items(meal_id, USER_ID)) == 1
    assert db.get_meal_by_id(meal_id, USER_ID)[4] == 180


def test_cannot_touch_other_users_meal():
    meal_id, result = add_breakfast()

    assert db.update_meal(meal_id, OTHER_USER, "взлом", result) is False
    assert db.get_meal_items(meal_id, OTHER_USER) == []

    db.delete_meal(meal_id, OTHER_USER)
    assert db.get_meal_by_id(meal_id, USER_ID) is not None


def test_delete_meal_removes_items():
    meal_id, _ = add_breakfast()
    db.delete_meal(meal_id, USER_ID)

    assert db.get_meal_by_id(meal_id, USER_ID) is None
    db.cursor.execute("SELECT COUNT(*) FROM meal_items WHERE meal_id = ?", (meal_id,))
    assert db.cursor.fetchone()[0] == 0


def test_copy_meal_to_today_copies_items():
    meal_id, _ = add_breakfast(day_offset=1)

    new_id = db.copy_meal_to_today(meal_id, USER_ID)

    assert new_id != meal_id
    assert len(db.get_meal_items(new_id, USER_ID)) == 2
    assert db.get_today_totals(USER_ID)[0] == 260


def test_frequent_meals_most_common_first_without_manual():
    add_breakfast()
    add_breakfast()
    db.add_meal(USER_ID, "банан 120 г", 107)
    db.add_meal(USER_ID, db.MANUAL_DESCRIPTION, 500)

    descriptions = [row[1] for row in db.get_frequent_meals(USER_ID)]

    assert descriptions == ["рыба 150 г, хлеб 30 г", "банан 120 г"]


def test_parallel_writes_are_not_lost():
    threads = [
        threading.Thread(target=db.add_meal, args=(USER_ID, f"тест {i}", 10))
        for i in range(50)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert db.get_today_totals(USER_ID)[0] == 500


# =========================
# ВЕС
# =========================


def test_one_weight_per_day():
    db.add_weight(USER_ID, 80.0)
    db.add_weight(USER_ID, 79.5)

    assert len(db.get_weights(USER_ID, "2000-01-01")) == 1
    assert db.get_last_weight(USER_ID)[1] == 79.5


def test_last_weight_on_or_before():
    db.cursor.executemany(
        "INSERT INTO weights (user_id, date, weight) VALUES (?, ?, ?)",
        [(USER_ID, "2026-01-01", 82), (USER_ID, "2026-01-10", 81)],
    )

    assert db.get_last_weight(USER_ID, on_or_before="2026-01-05") == ("2026-01-01", 82)
    assert db.get_last_weight(USER_ID) == ("2026-01-10", 81)


# =========================
# СОСТОЯНИЕ ДИАЛОГА
# =========================


def test_state_is_stored_in_db_and_merged():
    state.set_state(USER_ID, stage="editing", result={"items": []})
    state.set_state(USER_ID, draft_message_id=5)

    # Читаем напрямую из базы — как будто бот перезапустился
    assert db.load_state(USER_ID) == {
        "stage": "editing",
        "result": {"items": []},
        "draft_message_id": 5,
    }

    state.clear_state(USER_ID)
    assert state.get_state(USER_ID) == {}
