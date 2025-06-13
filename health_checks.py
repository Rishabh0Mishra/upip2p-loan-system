from fastapi import APIRouter
from sqlalchemy import text
from database import engine
import time
import psutil
from datetime import datetime, timedelta
import redis.asyncio as redis
from main import db_redis  # 🔥 Reuse from main.py

router = APIRouter(prefix="/health", tags=["health"])

startup_time = time.time()

def get_metric(query: str):
    with engine.connect() as conn:
        return conn.execute(text(query)).scalar() or 0

def get_last_hour_keys():
    now = datetime.utcnow()
    return [
        (now - timedelta(minutes=i)).strftime("traffic:%Y%m%d%H%M")
        for i in range(60)
    ]

async def get_api_calls_last_hour():
    if not db_redis:
        return 0
    keys = get_last_hour_keys()
    pipe = db_redis.pipeline()
    for key in keys:
        pipe.get(key)
    results = await pipe.execute()
    return sum(int(val or 0) for val in results)

@router.get("/", summary="Basic health check", operation_id="health_check")
async def health_check():
    checks = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy", "latency": "<1ms"}
    except Exception as e:
        checks["database"] = {"status": "unhealthy", "error": str(e)}

    checks["system"] = {
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent
    }

    checks["application"] = {
        "uptime_seconds": round(time.time() - startup_time),
        "version": "1.0.0"
    }

    overall_status = "healthy" if all(
        check.get("status", "healthy") == "healthy"
        for check in checks.values() if isinstance(check, dict) and "status" in check
    ) else "unhealthy"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks
    }

@router.get("/metrics", summary="Detailed app metrics", operation_id="get_metrics")
async def get_metrics():
    return {
        "active_loans": get_metric("SELECT COUNT(*) FROM loans WHERE status = 'active'"),
        "pending_requests": get_metric("SELECT COUNT(*) FROM notifications WHERE status = 'pending'"),
        "total_users": get_metric("SELECT COUNT(*) FROM users WHERE deleted_at IS NULL"),
        "notifications_sent_today": get_metric("SELECT COUNT(*) FROM notifications WHERE sent_at >= CURRENT_DATE"),
        "api_calls_last_hour": await get_api_calls_last_hour()
    }
