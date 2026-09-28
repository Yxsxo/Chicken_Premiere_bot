import os
import json
import base64
import logging

import anthropic
from dotenv import load_dotenv

import nutrition

load_dotenv()

logger = logging.getLogger(__name__)

client = anthropic.Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    timeout=30,  # сколько секунд ждать ответа, дальше — ошибка
    max_retries=2,  # при сбое сети или перегрузке SDK сам повторит запрос
)

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Ты — помощник по подсчёту калорий. Пользователь пишет тебе, что он съел, обычным языком на русском, или присылает фото еды.

Твоя задача:
1. Разбить сообщение (или то, что на фото) на отдельные продукты/блюда.
2. Определить вес порции каждого продукта в граммах. По фото оценивай размер порции по тарелке, приборам и другим предметам рядом.
3. Для каждого продукта также указать "quantity" — количество так, как человек написал бы его естественно: для штучных продуктов (яйца, бутерброды, бананы, котлеты и т.п.) — в штуках, например "4 шт"; для остального (рис, мясо порцией, салат и т.п.) — в граммах, например "180 г".
4. Посчитать калории и БЖУ (белки, жиры, углеводы) для каждого продукта.

Отвечай СТРОГО в формате JSON, без пояснений вокруг, без markdown-разметки (без ```), только сам JSON, в такой структуре:

{
  "items": [
    {"name": "название продукта в единственном числе", "quantity": "количество текстом, например 4 шт или 180 г", "grams": число, "kcal": число, "protein": число, "fat": число, "carbs": число}
  ]
}

"grams" — это всегда вес в граммах числом (используется для расчётов), а "quantity" — то же самое количество, но по-человечески (штуки или граммы текстом). Все числа — целые или с одним знаком после запятой.
Если в сообщении или на фото нет еды или напитков, верни {"items": []}.
Никакого текста, кроме этого JSON, в ответе быть не должно."""


class LLMUnavailableError(Exception):
    """LLM не ответил: нет сети, таймаут, сервис перегружен, неверный ключ."""


def _extract_json(raw_text):
    """Вырезает JSON из ответа, даже если модель добавила ``` или текст вокруг."""
    start = raw_text.find("{")
    end = raw_text.rfind("}")

    if start == -1 or end == -1:
        return None

    return raw_text[start : end + 1]


def _to_number(value):
    """Число из ответа модели: 120, 120.5 или даже строка "120,5"."""
    return float(str(value).replace(",", "."))


def _parse_result(raw_text):
    """Проверяет ответ модели и приводит его к нашему формату. None — если разобрать не вышло."""
    json_text = _extract_json(raw_text)

    if json_text is None:
        return None

    try:
        data = json.loads(json_text)
        items = []

        for item in data["items"]:
            grams = round(_to_number(item["grams"]))
            items.append(
                {
                    "name": str(item["name"]),
                    "quantity": str(item.get("quantity") or f"{grams} г"),
                    "grams": grams,
                    "kcal": round(_to_number(item["kcal"])),
                    "protein": round(_to_number(item.get("protein", 0)), 1),
                    "fat": round(_to_number(item.get("fat", 0)), 1),
                    "carbs": round(_to_number(item.get("carbs", 0)), 1),
                }
            )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return None

    if not items:
        return None

    # Итоги считаем сами из продуктов: модель иногда ошибается в сложении
    return nutrition.make_result(items)


def _ask(content):
    """Отправляет сообщение модели и разбирает ответ. content — текст или список блоков."""
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
    except anthropic.AnthropicError as error:
        logger.warning("LLM недоступен: %s: %s", type(error).__name__, error)
        raise LLMUnavailableError(str(error)) from error

    raw_text = response.content[0].text
    result = _parse_result(raw_text)

    if result is None:
        logger.info("Не удалось разобрать ответ LLM: %r", raw_text[:500])

    return result


def analyze_food(food_text, grams_text=None, image_bytes=None):
    """Разбирает еду по тексту и/или фото. Возвращает dict или None (не похоже на еду).
    Если LLM недоступен — бросает LLMUnavailableError."""
    if image_bytes is not None:
        caption = (
            f"Подпись к фото: {food_text}" if food_text else "Что за еда на фото?"
        )
        # Картинку передаём прямо в запросе, закодированной в base64
        return _ask(
            [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",  # Telegram присылает фото в JPEG
                        "data": base64.b64encode(image_bytes).decode("ascii"),
                    },
                },
                {"type": "text", "text": caption},
            ]
        )

    if grams_text:
        return _ask(
            f"Продукты: {food_text}\n"
            f"Пользователь указал точный вес порций: {grams_text}\n\n"
            "Используй именно эти граммы, не меняй и не оценивай их заново — "
            "только посчитай калории и БЖУ по указанному весу. "
            "В поле quantity в этом случае укажи граммы, которые дал пользователь."
        )

    return _ask(food_text)


def correct_result(result, correction_text):
    """Правка готового разбора словами: «рыбы было 200 г, хлеба не было»."""
    current_items = json.dumps(result["items"], ensure_ascii=False)

    return _ask(
        f"Вот текущий разбор приёма пищи:\n{current_items}\n\n"
        f"Пользователь поправляет: {correction_text}\n\n"
        "Внеси эти исправления и верни ПОЛНЫЙ список продуктов в том же JSON-формате. "
        "Продукты, которые пользователь не упоминал, оставь без изменений."
    )
