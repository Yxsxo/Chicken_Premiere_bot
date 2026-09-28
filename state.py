"""Состояние диалога: на каком шаге пользователь и что он уже ввёл.
Хранится в базе (таблица user_states), поэтому переживает перезапуск бота."""

import db


def get_state(user_id):
    return db.load_state(user_id)


def set_state(user_id, **kwargs):
    db.update_state(user_id, kwargs)


def clear_state(user_id):
    db.delete_state(user_id)
