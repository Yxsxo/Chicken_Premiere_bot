import os
import json

from dotenv import load_dotenv
from anthropic import Anthropic

load_dotenv()

client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """Ты — помощник по подсчёту калорий. Пользователь пишет тебе, что он съел, обычным языком на русском.

Твоя задача:
1. Разбить сообщение на отдельные продукты/блюда.
2. Определить вес порции каждого продукта в граммах.
3. Для каждого продукта также указать "quantity" — количество так, как человек написал бы его естественно: для штучных продуктов (яйца, бутерброды, бананы, котлеты и т.п.) — в штуках, например "4 шт"; для остального (рис, мясо порцией, салат и т.п.) — в граммах, например "180 г".
4. Посчитать калории и БЖУ (белки, жиры, углеводы) для каждого продукта и суммарно.

Отвечай СТРОГО в формате JSON, без пояснений вокруг, без markdown-разметки (без ```), только сам JSON, в такой структуре:

{
  "items": [
    {"name": "название продукта в единственном числе", "quantity": "количество текстом, например 4 шт или 180 г", "grams": число, "kcal": число, "protein": число, "fat": число, "carbs": число}
  ],
  "total_kcal": число,
  "total_protein": число,
  "total_fat": число,
  "total_carbs": число
}

"grams" — это всегда вес в граммах числом (используется для расчётов), а "quantity" — то же самое количество, но по-человечески (штуки или граммы текстом). Все числа — целые или с одним знаком после запятой. Никакого текста, кроме этого JSON, в ответе быть не должно."""


def _extract_json(raw_text):
    text = raw_text.strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]

    return text.strip()


def analyze_food(food_text, grams_text=None):
    if grams_text:
        user_message = (
            f"Продукты: {food_text}\n"
            f"Пользователь указал точный вес порций: {grams_text}\n\n"
            "Используй именно эти граммы, не меняй и не оценивай их заново — "
            "только посчитай калории и БЖУ по указанному весу. "
            "В поле quantity в этом случае укажи граммы, которые дал пользователь."
        )
    else:
        user_message = food_text

    response = client.messages.create(
        model=MODEL,
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = response.content[0].text

    try:
        return json.loads(_extract_json(raw_text))
    except json.JSONDecodeError:
        return None
