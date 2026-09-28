import io
from datetime import datetime, timedelta

from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure

import clock
import db
import formatting


def _figure_to_png(figure):
    image = io.BytesIO()
    figure.savefig(image, format="png")
    image.seek(0)
    return image


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
    """График в памяти (BytesIO) — без общего файла на диске,
    чтобы два одновременных отчёта не перезаписали друг друга."""
    data = db.get_calories_by_day(user_id, start_date, end_date)

    if not data:
        return None

    dates = [datetime.strptime(row[0], "%Y-%m-%d").strftime("%d.%m") for row in data]
    calories = [row[1] for row in data]

    period_label = (
        f"{formatting.format_date_ddmmyyyy(start_date)} — "
        f"{formatting.format_date_ddmmyyyy(end_date)}"
    )

    # Figure напрямую, без pyplot: pyplot хранит «текущий график» глобально
    # и не рассчитан на работу из нескольких потоков
    figure = Figure(figsize=(8, 4))
    axes = figure.subplots()
    axes.bar(dates, calories, color="#4CAF50")
    axes.set_title(f"Калории: {period_label}")
    axes.set_xlabel("Дата")
    axes.set_ylabel("Ккал")
    axes.tick_params(axis="x", rotation=45)
    figure.tight_layout()

    return _figure_to_png(figure)


def build_weight_image(user_id, days=90):
    """Линия веса за последние days дней. None — если записей меньше двух."""
    start_date = (clock.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    data = db.get_weights(user_id, start_date)

    if len(data) < 2:
        return None

    dates = [datetime.strptime(row[0], "%Y-%m-%d") for row in data]
    weights = [row[1] for row in data]

    figure = Figure(figsize=(8, 4))
    axes = figure.subplots()
    axes.plot(dates, weights, marker="o", color="#2196F3")
    axes.set_title(f"Вес за {days} дней")
    axes.set_ylabel("Кг")
    axes.grid(alpha=0.3)
    axes.xaxis.set_major_formatter(DateFormatter("%d.%m"))
    figure.autofmt_xdate()
    figure.tight_layout()

    return _figure_to_png(figure)
