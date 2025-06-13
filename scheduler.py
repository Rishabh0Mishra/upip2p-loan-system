from apscheduler.schedulers.background import BackgroundScheduler
from dependencies import get_db
from notification_service import NotificationService

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_payment_reminders, 'interval', hours=24)
    scheduler.add_job(check_and_send_overdue_notifications, 'interval', hours=24)
    scheduler.start()
    return scheduler

def check_and_send_payment_reminders():
    db = next(get_db())
    notification_service = NotificationService(db)
    notification_service.schedule_payment_reminders()
    db.close()

def check_and_send_overdue_notifications():
    db = next(get_db())
    notification_service = NotificationService(db)
    notification_service.check_overdue_payments()
    db.close()
