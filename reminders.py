import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler

import clock
import db
import formatting

logger = logging.getLogger(__name__)


def build_reminder_text(user_id, daily_goal):
    """Если за день ничего не записано — мягкий пинок, иначе — итог дня.
    По понедельникам ещё просим взвеситься, если неделю не взвешивался."""
    totals = db.get_today_totals(user_id)

    if not db.get_today_meals(user_id):
        text = "🔔 Сегодня ещё нет записей. Напиши, что ел, — я посчитаю 🙂"
    else:
        protein_goal = db.get_protein_goal(user_id)
        text = "🌙 Итог дня\n\n" + formatting.format_day_summary(
            totals, daily_goal, protein_goal
        )

    now = clock.now()
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    last_weight = db.get_last_weight(user_id)

    if now.weekday() == 0 and (last_weight is None or last_weight[0] <= week_ago):
        text += "\n\n⚖️ Новая неделя — самое время взвеситься! Нажми «⚖️ Вес»."

    return text


def start_reminders(bot):
    scheduler = BackgroundScheduler(timezone=clock.TIMEZONE)

    def check_and_send():
        now = clock.now()

        for (
            user_id,
            chat_id,
            daily_goal,
            reminder_hour,
            reminder_minute,
        ) in db.get_all_known_users():
            if reminder_hour == now.hour and reminder_minute == now.minute:
                try:
                    bot.send_message(chat_id, build_reminder_text(user_id, daily_goal))
                except Exception as error:
                    # например, если пользователь заблокировал бота
                    logger.info("Не удалось отправить напоминание %s: %s", user_id, error)

    scheduler.add_job(check_and_send, "cron", minute="*")
    scheduler.start()

    return scheduler
