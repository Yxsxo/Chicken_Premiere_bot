"""Арифметика КБЖУ: итоги по продуктам и пересчёт продукта под новый вес."""


def make_result(items):
    """Собирает результат разбора: продукты + итоги, посчитанные из продуктов."""
    return {
        "items": items,
        "total_kcal": sum(item["kcal"] for item in items),
        "total_protein": round(sum(item["protein"] for item in items), 1),
        "total_fat": round(sum(item["fat"] for item in items), 1),
        "total_carbs": round(sum(item["carbs"] for item in items), 1),
    }


def scale_item(item, new_grams):
    """Тот же продукт, но другой вес: калории и БЖУ меняются пропорционально.
    Было 150 г и 180 ккал → стало 200 г и 240 ккал."""
    old_grams = item["grams"] or 1  # защита от деления на ноль
    ratio = new_grams / old_grams

    return {
        **item,
        "grams": new_grams,
        "quantity": f"{new_grams} г",
        "kcal": round(item["kcal"] * ratio),
        "protein": round(item["protein"] * ratio, 1),
        "fat": round(item["fat"] * ratio, 1),
        "carbs": round(item["carbs"] * ratio, 1),
    }
