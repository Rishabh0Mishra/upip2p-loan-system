from apscheduler.schedulers.background import BackgroundScheduler
from dependencies import get_db
from notification_service import NotificationService
import asyncio
from fastapi import FastAPI
from sqlalchemy.orm import Session
from database import SessionLocal
from emi_processor import process_due_emis
import logging

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 10  # Adjustable: 10 or 30 seconds for real-time demo

def start_scheduler(app: FastAPI):
    # Start APScheduler for reminders and overdue notifications
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_and_send_payment_reminders, 'interval', hours=24)
    scheduler.add_job(check_and_send_overdue_notifications, 'interval', hours=24)
    scheduler.start()

    # Attach EMI loop to FastAPI startup
    @app.on_event("startup")
    async def launch_emi_scheduler():
        logger.info("Starting EMI processing scheduler loop...")
        asyncio.create_task(emi_scheduler_loop())

def check_and_send_payment_reminders():
    db = next(get_db())
    try:
        notification_service = NotificationService(db)
        notification_service.schedule_payment_reminders()
    except Exception as e:
        logger.error(f"Reminder job failed: {e}")
    finally:
        db.close()

def check_and_send_overdue_notifications():
    db = next(get_db())
    try:
        notification_service = NotificationService(db)
        notification_service.check_overdue_payments()
    except Exception as e:
        logger.error(f"Overdue job failed: {e}")
    finally:
        db.close()

async def emi_scheduler_loop():
    while True:
        try:
            db: Session = SessionLocal()
            process_due_emis(db)
        except Exception as e:
            logger.error(f"EMI scheduler loop error: {e}")
        finally:
            db.close()
        await asyncio.sleep(INTERVAL_SECONDS)
