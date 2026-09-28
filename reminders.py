from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

import db


def start_reminders(bot):
    scheduler = BackgroundScheduler()

    def check_and_send():
        now = datetime.now()

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
                        chat_id, "🔔 Не забыл записать сегодняшние приёмы пищи?"
                    )
                except Exception:
                    pass  # например, если пользователь заблокировал бота

    scheduler.add_job(check_and_send, "cron", minute="*")
    scheduler.start()

    return scheduler
