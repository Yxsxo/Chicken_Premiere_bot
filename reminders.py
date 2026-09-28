import logging

from apscheduler.schedulers.background import BackgroundScheduler

import clock
import db

logger = logging.getLogger(__name__)


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
                    bot.send_message(
                        chat_id, "🔔 Не забудь записать сегодняшние приёмы пищи!"
                    )
                except Exception as error:
                    # например, если пользователь заблокировал бота
                    logger.info("Не удалось отправить напоминание %s: %s", user_id, error)

    scheduler.add_job(check_and_send, "cron", minute="*")
    scheduler.start()

    return scheduler
