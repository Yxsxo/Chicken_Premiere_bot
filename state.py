user_states = {}


def get_state(user_id):
    return user_states.get(user_id, {})


def set_state(user_id, **kwargs):
    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id].update(kwargs)


def clear_state(user_id):
    user_states.pop(user_id, None)
