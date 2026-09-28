import nutrition
from conftest import item


def test_make_result_sums_items():
    result = nutrition.make_result(
        [item("рыба", 150, 180, 30, 6, 0), item("хлеб", 30, 80, 2.5, 1, 15.2)]
    )

    assert result["total_kcal"] == 260
    assert result["total_protein"] == 32.5
    assert result["total_fat"] == 7
    assert result["total_carbs"] == 15.2


def test_make_result_empty():
    assert nutrition.make_result([])["total_kcal"] == 0


def test_scale_item_is_proportional():
    fish = item("рыба", 150, 180, 30, 6, 0)

    scaled = nutrition.scale_item(fish, 200)

    assert scaled["grams"] == 200
    assert scaled["kcal"] == 240
    assert scaled["protein"] == 40
    assert scaled["fat"] == 8
    assert scaled["quantity"] == "200 г"
    assert scaled["name"] == "рыба"


def test_scale_item_does_not_change_original():
    fish = item("рыба", 150, 180)
    nutrition.scale_item(fish, 300)
    assert fish["grams"] == 150


def test_scale_item_from_zero_grams_does_not_crash():
    assert nutrition.scale_item(item("вода", 0, 0), 100)["grams"] == 100
