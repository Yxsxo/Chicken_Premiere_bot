GENDER_MALE = "male"
GENDER_FEMALE = "female"

ACTIVITY_MULTIPLIERS = {
    "low": 1.2,  # мало или нет физической активности
    "medium": 1.375,  # лёгкие тренировки 1-3 раза в неделю
    "high": 1.55,  # тренировки 4-5 раз в неделю
    "very_high": 1.725,  # тренировки почти каждый день / физическая работа
}

GOAL_MULTIPLIERS = {
    "lose": 0.85,  # похудение
    "maintain": 1.0,  # удержание веса
    "gain": 1.15,  # массонабор
}


def calculate_bmr(weight_kg, height_cm, age, gender):
    """Базовый обмен веществ, формула Миффлина - Сан Жеора."""
    if gender == GENDER_MALE:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age + 5
    else:
        return 10 * weight_kg + 6.25 * height_cm - 5 * age - 161


def calculate_daily_goal(weight_kg, height_cm, age, gender, activity, goal):
    bmr = calculate_bmr(weight_kg, height_cm, age, gender)
    tdee = bmr * ACTIVITY_MULTIPLIERS[activity]
    target = tdee * GOAL_MULTIPLIERS[goal]
    return round(target / 10) * 10  # округляем до десятков
