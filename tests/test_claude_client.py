"""Разбор ответа LLM и обработка ошибок API — без настоящих запросов."""

from types import SimpleNamespace as NS

import anthropic
import pytest

import claude_client
from claude_client import _parse_result

GOOD = (
    '{"items": [{"name": "яйцо", "quantity": "3 шт", "grams": 150, "kcal": 235,'
    ' "protein": 19, "fat": 16.5, "carbs": 1}]}'
)


def test_parse_normal_answer():
    result = _parse_result(GOOD)

    assert result["items"][0]["name"] == "яйцо"
    assert result["items"][0]["quantity"] == "3 шт"
    assert result["total_kcal"] == 235


def test_parse_answer_wrapped_in_markdown_and_text():
    raw = "Вот разбор:\n```json\n" + GOOD + "\n```\nПриятного аппетита!"
    assert _parse_result(raw)["total_kcal"] == 235


def test_parse_numbers_as_strings_with_comma():
    raw = '{"items": [{"name": "рис", "grams": "180", "kcal": "216,4", "protein": "4,5"}]}'
    result = _parse_result(raw)

    assert result["items"][0]["kcal"] == 216
    assert result["items"][0]["protein"] == 4.5


def test_parse_fills_missing_quantity_and_macros():
    result = _parse_result('{"items": [{"name": "рис", "grams": 180, "kcal": 216}]}')

    assert result["items"][0]["quantity"] == "180 г"
    assert result["items"][0]["fat"] == 0


def test_totals_are_recalculated_not_trusted():
    raw = (
        '{"items": [{"name": "a", "grams": 1, "kcal": 100}, {"name": "b", "grams": 1, "kcal": 50}],'
        ' "total_kcal": 9999}'
    )
    assert _parse_result(raw)["total_kcal"] == 150


@pytest.mark.parametrize(
    "raw",
    [
        '{"items": []}',  # не еда
        "Извините, я не понял",  # не JSON
        '{"items": [{"name": "рис"',  # обрезанный JSON
        '{"items": [{"name": "рис", "grams": 180}]}',  # нет калорий
        '{"items": [{"name": "рис", "grams": "много", "kcal": 1}]}',  # не число
        "[1, 2, 3]",  # не тот формат
        '{"items": "рис"}',
    ],
)
def test_parse_bad_answers_return_none(raw):
    assert _parse_result(raw) is None


def test_api_error_becomes_llm_unavailable(monkeypatch):
    def broken_create(**kwargs):
        raise anthropic.AnthropicError("нет сети")

    monkeypatch.setattr(claude_client, "client", NS(messages=NS(create=broken_create)))

    with pytest.raises(claude_client.LLMUnavailableError):
        claude_client.analyze_food("3 яйца")


def test_photo_is_sent_as_image_block(monkeypatch):
    sent = []
    monkeypatch.setattr(claude_client, "_ask", lambda content: sent.append(content))

    claude_client.analyze_food("на обед", image_bytes=b"jpeg-bytes")

    image_block, text_block = sent[0]
    assert image_block["type"] == "image"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert "на обед" in text_block["text"]


def test_correction_sends_current_items(monkeypatch):
    sent = []
    monkeypatch.setattr(claude_client, "_ask", lambda content: sent.append(content))

    claude_client.correct_result(_parse_result(GOOD), "яиц было два")

    assert "яйцо" in sent[0]
    assert "яиц было два" in sent[0]
