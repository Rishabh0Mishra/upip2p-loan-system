from fastapi import APIRouter
from database import SessionLocal
from redis_config import db_redis  # ✅ Make sure this import is correct
import models
import time
from datetime import datetime, timedelta

router = APIRouter(prefix="/health", tags=["health"])

app_start_time = time.time()

@router.get("/")
def health_check():
    return {"status": "ok"}

@router.get("/metrics")
async def get_metrics():
    db = SessionLocal()
    total_loans = db.query(models.Loan).count()
    total_users = db.query(models.User).count()
    document_uploads = db.query(models.LoanDocument).count()
    uptime_seconds = int(time.time() - app_start_time)

    # ✅ Count of fully signed agreements
    agreements_signed = db.query(models.Loan).filter(models.Loan.status == "completed").count()

    # ✅ API traffic tracking (last 60 minutes)
    now = datetime.utcnow()
    traffic_last_hour = 0
    for i in range(60):
        minute_key = (now - timedelta(minutes=i)).strftime("traffic:%Y%m%d%H%M")
        count = await db_redis.get(minute_key)
        traffic_last_hour += int(count or 0)

    return {
        "uptime_seconds": uptime_seconds,
        "total_loans": total_loans,
        "total_users": total_users,
        "document_uploads": document_uploads,
        "agreements_signed": agreements_signed,
        "api_calls_last_hour": traffic_last_hour
    }

