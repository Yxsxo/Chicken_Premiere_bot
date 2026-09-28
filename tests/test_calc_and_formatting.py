import pytest

import calc
import formatting
from conftest import item


# =========================
# РАСЧЁТ НОРМЫ
# =========================


def test_bmr_mifflin_st_jeor():
    # 10*80 + 6.25*180 - 5*30 + 5 = 1780
    assert calc.calculate_bmr(80, 180, 30, calc.GENDER_MALE) == 1780
    # то же для женщины: -161 вместо +5
    assert calc.calculate_bmr(80, 180, 30, calc.GENDER_FEMALE) == 1614


def test_daily_goal_rounded_to_tens():
    goal = calc.calculate_daily_goal(80, 180, 30, calc.GENDER_MALE, "medium", "lose")
    # 1780 * 1.375 * 0.85 = 2080.4 → 2080
    assert goal == 2080


def test_protein_goal():
    assert calc.calculate_protein_goal(80, "lose") == 145  # 80 * 1.8 = 144 → 145
    assert calc.calculate_protein_goal(80, "maintain") == 110  # 112 → 110


# =========================
# ТЕКСТЫ
# =========================


@pytest.mark.parametrize(
    "value, bar",
    [
        (0, "⬜" * 10),
        (1100, "🟩" * 5 + "⬜" * 5),
        (2200, "🟩" * 10),
        (2600, "🟥" * 10),  # перебор
    ],
)
def test_progress_bar(value, bar):
    assert formatting.progress_bar(value, 2200) == bar


def test_item_line_shows_pieces_and_grams():
    assert formatting.format_item_line(item("яйцо", 100, 157, quantity="2 шт")) == (
        "Яйцо — 2 шт (100 г) — 157 ккал"
    )
    assert formatting.format_item_line(item("рис", 180, 216)) == "Рис — 180 г — 216 ккал"


def test_day_summary_over_goal():
    text = formatting.format_day_summary((2500, 100, 80, 300), 2200, protein_goal=120)

    assert "Перебор: 300 ккал" in text
    assert "Б: 100 / 120 г" in text


def test_macros_without_trailing_zero():
    import nutrition

    result = nutrition.make_result([item("рыба", 100, 120, protein=20.0, fat=4.5)])
    text = formatting.format_food_result(result, "заголовок")

    assert "Б: 20 г" in text  # а не 20.0
    assert "Ж: 4.5 г" in text


@pytest.mark.parametrize(
    "diff, expected",
    [(-0.4, "−0.4 кг"), (1.25, "+1.2 кг"), (0.01, "без изменений")],
)
def test_weight_change(diff, expected):
    assert formatting.format_weight_change(diff) == expected
