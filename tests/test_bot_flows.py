"""Сценарии «как у пользователя»: пишем боту, жмём кнопки, проверяем ответы и базу."""

from datetime import datetime

import clock
import db
import reminders
from conftest import USER_ID, item

FISH = item("рыба", 150, 180, 30, 6, 0)
BREAD = item("хлеб", 30, 80, 2.5, 1, 15, quantity="1 шт")


def saved_meals():
    return db.get_last_meals(USER_ID, limit=100)


def open_editor(chat, llm):
    llm.answer(FISH, BREAD)
    chat.send("на завтрак рыба и хлеб")
    chat.click("portion_estimate")
    chat.click("confirm_edit")


# =========================
# НОВАЯ ЗАПИСЬ И РЕДАКТОР
# =========================


def test_estimate_and_save(chat, llm):
    llm.answer(FISH, BREAD)

    chat.send("на завтрак рыба и хлеб")
    assert "Как считаем порцию?" in chat.last_text

    chat.click("portion_estimate")
    assert "Рыба — 150 г — 180 ккал" in chat.last_text
    assert "Приём пищи: завтрак" in chat.last_text

    chat.click("confirm_save")
    assert "✅ Записано!" in chat.last_text

    (meal,) = saved_meals()
    assert meal[4] == 260  # калории
    assert meal[5] == "завтрак"


def test_edit_item_weight_recalculates(chat, llm):
    """Тот самый случай: не согласен с весом рыбы — поправил, а не ввёл заново."""
    open_editor(chat, llm)

    chat.click("edit_item_0")
    chat.click("edit_grams_0")
    chat.send("200")

    assert "Рыба — 200 г — 240 ккал" in chat.last_text
    assert len(llm.requests) == 1  # пересчёт без повторного запроса к LLM

    chat.click("confirm_save")
    meal_id = saved_meals()[0][0]
    assert db.get_meal_items(meal_id, USER_ID)[0]["grams"] == 200
    assert saved_meals()[0][4] == 320


def test_edit_item_weight_rejects_garbage(chat, llm):
    open_editor(chat, llm)
    chat.click("edit_item_0")
    chat.click("edit_grams_0")

    chat.send("много")

    assert "Напиши вес числом" in chat.last_text


def test_remove_and_add_items(chat, llm):
    open_editor(chat, llm)

    chat.click("edit_item_1")
    chat.click("edit_remove_1")
    assert "Хлеб" not in chat.last_text

    llm.answer(item("соус", 30, 60))
    chat.click("edit_add")
    chat.send("соус 30 г")
    assert "Соус — 30 г — 60 ккал" in chat.last_text

    chat.click("confirm_save")
    assert saved_meals()[0][4] == 240


def test_text_correction_goes_to_llm_with_current_items(chat, llm):
    open_editor(chat, llm)

    llm.answer(FISH)  # «хлеба не было»
    chat.send("хлеба не было")

    assert "хлеба не было" in llm.requests[-1]
    assert "рыба" in llm.requests[-1]  # модель видит текущий список
    assert "Хлеб" not in chat.last_text


def test_empty_draft_cannot_be_saved(chat, llm):
    llm.answer(FISH)
    chat.send("рыба")
    chat.click("portion_estimate")
    chat.click("confirm_edit")
    chat.click("edit_item_0")
    chat.click("edit_remove_0")

    assert "✅ Записать" not in chat.last_buttons
    assert saved_meals() == []


def test_old_draft_buttons_are_ignored(chat, llm, telegram):
    llm.answer(FISH)
    chat.send("рыба")
    chat.click("portion_estimate")
    old_draft = chat.last_id

    chat.send("хлеб")  # начали новую запись

    chat.click("confirm_save", message_id=old_draft)

    assert telegram.toasts[-1].startswith("Этот черновик устарел")
    assert saved_meals() == []


def test_draft_survives_restart(chat, llm):
    """Состояние в базе: после «перезапуска» кнопки черновика продолжают работать."""
    open_editor(chat, llm)
    assert db.load_state(USER_ID)["stage"] == "editing"

    chat.click("confirm_save")
    assert len(saved_meals()) == 1


def test_llm_unavailable_keeps_buttons(chat, llm):
    llm.unavailable = True
    chat.send("рыба")
    chat.click("portion_estimate")

    assert "не отвечает" in chat.last_text
    assert "🤖 Оцени сам" in chat.last_buttons  # можно нажать ещё раз

    llm.unavailable = False
    llm.answer(FISH)
    chat.click("portion_estimate")
    assert "Рыба" in chat.last_text


def test_not_food(chat, llm):
    llm.result = None
    chat.send("как дела?")
    chat.click("portion_estimate")

    assert "Не получилось разобрать" in chat.last_text


def test_grams_given_by_user(chat, llm):
    llm.answer(item("рис", 200, 260))
    chat.send("рис")
    chat.click("portion_grams")
    chat.send("рис 200 г")

    assert "Используй именно эти граммы" in llm.requests[-1]
    assert "Рис — 200 г" in chat.last_text


def test_yesterday(chat, llm):
    llm.answer(item("пельмени", 300, 750))
    chat.send("вчера на ужин пельмени")
    assert "Запишу на вчера" in chat.last_text

    chat.click("portion_estimate")
    chat.click("confirm_save")

    assert "Записано на вчера" in chat.last_text
    assert db.get_today_totals(USER_ID)[0] == 0


def test_photo(chat, llm):
    llm.answer(FISH)
    chat.send_photo(caption="на обед")

    assert llm.requests[-1][0]["type"] == "image"
    assert "Вот что я вижу на фото" in chat.last_text
    assert "Приём пищи: обед" in chat.last_text

    chat.click("confirm_save")
    assert saved_meals()[0][5] == "обед"


# =========================
# ПРОСТОЙ ВВОД
# =========================


def test_manual_calories(chat):
    chat.send("450")
    assert "Записал 450 ккал" in chat.last_text

    chat.send("99999")
    assert "опечатку" in chat.last_text
    assert len(saved_meals()) == 1


def test_weight_validation_and_change(chat):
    chat.send("⚖️ Вес")
    chat.send("-5")
    assert "Не получилось распознать вес" in chat.last_text

    chat.send("78,4")
    assert "Записал: 78.4 кг" in chat.last_text


def test_report_period_must_be_ordered(chat):
    chat.send("📈 Отчёт")
    chat.click("reportperiod_custom")
    chat.send("14.09.2026-01.09.2026")

    assert "раньше конца" in chat.last_text


def test_week_report_image(chat, telegram):
    db.add_meal(USER_ID, "тест", 500)
    chat.send("📈 Отчёт")
    chat.click("reportperiod_week")
    chat.click("reportformat_image")

    assert telegram.photos[-1][:4] == b"\x89PNG"


def test_protein_goal_shown_today(chat):
    chat.send("⚙️ Настройки")
    chat.click("settings_protein")
    chat.send("120")
    chat.send("📊 Сегодня")

    assert "Б: 0 / 120 г" in chat.last_text


# =========================
# ИСТОРИЯ И ПОВТОР
# =========================


def test_delete_asks_for_confirmation(chat):
    meal_id = db.add_meal(USER_ID, "банан", 100)
    chat.send("📜 История")
    chat.click(f"histopen_{meal_id}")
    chat.click(f"histdel_{meal_id}")

    assert "Удалить эту запись?" in chat.last_text
    assert len(saved_meals()) == 1  # пока не подтвердили — не удаляем

    chat.click(f"histdelok_{meal_id}")
    assert saved_meals() == []


def test_edit_saved_meal_from_history(chat, llm):
    llm.answer(FISH, BREAD)
    chat.send("рыба и хлеб")
    chat.click("portion_estimate")
    chat.click("confirm_save")
    meal_id = saved_meals()[0][0]

    chat.send("📜 История")
    chat.click(f"histopen_{meal_id}")
    chat.click(f"histedit_{meal_id}")
    chat.click("edit_item_1")
    chat.click("edit_remove_1")
    chat.click("confirm_save")

    assert "Запись обновлена" in chat.last_text
    assert len(saved_meals()) == 1  # изменили, а не добавили новую
    assert saved_meals()[0][4] == 180


def test_repeat_and_undo(chat):
    db.add_meal(USER_ID, "овсянка 200 г", 300)

    chat.send("🔁 Повторить")
    chat.click(chat.tg.messages[chat.last_id]["buttons"][0][1])
    assert "Записал ещё раз" in chat.last_text
    assert len(saved_meals()) == 2

    new_id = saved_meals()[0][0]
    chat.click(f"undo_{new_id}")
    assert len(saved_meals()) == 1


# =========================
# НАПОМИНАНИЯ
# =========================


def test_reminder_empty_day():
    assert "ещё нет записей" in reminders.build_reminder_text(USER_ID, 2200)


def test_reminder_day_summary():
    db.add_meal(USER_ID, "обед", 800)
    text = reminders.build_reminder_text(USER_ID, 2200)

    assert "Итог дня" in text
    assert "800 / 2200 ккал" in text


def test_reminder_asks_to_weigh_on_monday(monkeypatch):
    monday = datetime(2026, 9, 28, 21, 0, tzinfo=clock.TIMEZONE)
    monkeypatch.setattr(reminders.clock, "now", lambda: monday)

    assert "взвеситься" in reminders.build_reminder_text(USER_ID, 2200)
