from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

import db
import formatting


def build_text_report(user_id, start_date, end_date):
    data = db.get_calories_by_day(user_id, start_date, end_date)

    period_label = (
        f"{formatting.format_date_ddmmyyyy(start_date)} — "
        f"{formatting.format_date_ddmmyyyy(end_date)}"
    )

    if not data:
        return f"За период {period_label} записей нет."

    lines = [f"📈 Отчёт за {period_label}:\n"]

    total = 0
    for date, calories in data:
        lines.append(f"{formatting.format_date_with_weekday(date)}: {calories} ккал")
        total += calories

    average = total / len(data)

    lines.append(f"\nДней с записями: {len(data)}")
    lines.append(f"Суммарно: {total} ккал")
    lines.append(f"В среднем за день: {average:.0f} ккал")

    return "\n".join(lines)


def build_image_report(user_id, start_date, end_date):
    data = db.get_calories_by_day(user_id, start_date, end_date)

    if not data:
        return None

    dates = [datetime.strptime(row[0], "%Y-%m-%d").strftime("%d.%m") for row in data]
    calories = [row[1] for row in data]

    period_label = (
        f"{formatting.format_date_ddmmyyyy(start_date)} — "
        f"{formatting.format_date_ddmmyyyy(end_date)}"
    )

    plt.figure(figsize=(8, 4))
    plt.bar(dates, calories, color="#4CAF50")
    plt.title(f"Калории: {period_label}")
    plt.xlabel("Дата")
    plt.ylabel("Ккал")
    plt.xticks(rotation=45)
    plt.tight_layout()

    path = "report.png"
    plt.savefig(path)
    plt.close()

    return path
