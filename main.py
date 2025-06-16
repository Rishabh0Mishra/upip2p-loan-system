from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from decimal import Decimal
from datetime import datetime
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import redis.asyncio as redis
import logging
import uuid
import time
import json
import threading


import models, schemas
from database import engine, Base
from scheduler import start_scheduler
from exceptions import LoanServiceException, InsufficientFundsException
from websocket_manager import manager
from email_utils import send_email

# Import Routers
from admin_routes import admin_router
from borrower_routes import borrower_router
from lender_routes import lender_router
from user_routes import user_router
from loan_routes import router as loan_router
from audit_routes import audit_router
from health_routes import router as health_router
from document_routes import router as document_router
from repayment_routes import router as repayment_router
from emi_worker import run_worker
from wallet_routes import wallet_router


# Shared dependencies and utils
from dependencies import (
    get_db,
    get_current_user,
    get_password_hash,
    authenticate_user,
    create_access_token,
    create_refresh_token,
)
from utils import sanitize_input

app = FastAPI()

# Logger setup
logger = logging.getLogger("uvicorn.error")

# Rate Limiter setup
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Create DB tables
Base.metadata.create_all(bind=engine)

# Redis client placeholder
db_redis = None

@app.on_event("startup")
async def startup_event():
    global db_redis
    db_redis = redis.from_url("redis://localhost:6379", encoding="utf-8", decode_responses=True)
    start_scheduler()

@app.on_event("shutdown")
async def shutdown_event():
    await db_redis.close()
    await db_redis.connection_pool.disconnect()

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
            return await call_next(request)

        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start_time = time.time()
        logger.info(f"API Request: id={request_id} method={request.method} path={request.url.path} client_ip={request.client.host}")

        # ✅ Track API traffic in Redis
        if db_redis:
            timestamp_key = datetime.utcnow().strftime("traffic:%Y%m%d%H%M")
            await db_redis.incr(timestamp_key)
            await db_redis.expire(timestamp_key, 3600 * 2)

        response = await call_next(request)

        process_time = time.time() - start_time
        logger.info(f"API Response: id={request_id} status_code={response.status_code} process_time={process_time:.4f}s")

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time"] = str(round(process_time, 4))

        return response

    
    

app.add_middleware(RequestLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["localhost", "127.0.0.1", "yourdomain.com", "*.yourdomain.com"],
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.exception_handler(LoanServiceException)
async def loan_service_exception_handler(request: Request, exc: LoanServiceException):
    return JSONResponse(status_code=400, content={"error": "Loan Service Error", "message": str(exc), "type": exc.__class__.__name__})

@app.exception_handler(InsufficientFundsException)
async def insufficient_funds_handler(request: Request, exc: InsufficientFundsException):
    return JSONResponse(status_code=400, content={"error": "Insufficient Funds", "message": "Lender does not have sufficient funds for this loan", "code": "INSUFFICIENT_FUNDS"})

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error. Please try again later."})

@app.post("/register", response_model=schemas.UserOut)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    clean_name = sanitize_input(user.name)
    clean_email = sanitize_input(user.email)
    clean_upi_id = sanitize_input(user.upi_id)

    if db.query(models.User).filter(
    models.User.email == clean_email,
    models.User.deleted_at.is_(None)
    ).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = get_password_hash(user.password)
    new_user = models.User(name=clean_name, email=clean_email, hashed_password=hashed_password, upi_id=clean_upi_id, role=user.role or "borrower")
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    wallet = models.Wallet(user_id=new_user.id, balance=Decimal("0.00"))
    db.add(wallet)
    db.commit()

    token = str(uuid.uuid4())
    existing_token = db.query(models.EmailVerificationToken).filter_by(user_id=new_user.id).first()
    if existing_token:
        existing_token.token = token
        existing_token.is_verified = False
    else:
        db.add(models.EmailVerificationToken(user_id=new_user.id, token=token))
    db.commit()

    verification_link = f"http://localhost:8000/user/verify-email?token={token}"
    html_content = f"""
        <html><body><h2>👋 Welcome to UPI P2P!</h2><p>Click to verify:</p>
        <a href=\"{verification_link}\">✅ Verify Email</a>
        <p>If not clickable, paste this: {verification_link}</p></body></html>
    """
    send_email(to_email=new_user.email, subject="Verify your email", html_content=html_content)
    return new_user

@app.post("/token")
@limiter.limit("5/minute")
async def login_for_access_token(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(db, user.id)
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}

@app.post("/refresh-token")
def refresh_access_token(request: schemas.TokenRequest, db: Session = Depends(get_db)):
    token_obj = db.query(models.RefreshToken).filter(models.RefreshToken.token == request.refresh_token).first()
    if not token_obj or token_obj.revoked or token_obj.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    access_token = create_access_token(data={"sub": token_obj.user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/logout")
def logout(request: schemas.TokenRequest, db: Session = Depends(get_db)):
    token_obj = db.query(models.RefreshToken).filter(models.RefreshToken.token == request.refresh_token).first()
    if token_obj:
        token_obj.revoked = True
        db.commit()
    return {"msg": "Logged out successfully"}

@app.get("/users/me", response_model=schemas.UserOut)
async def read_users_me(current_user: models.User = Depends(get_current_user)):
    cache_key = f"user:{current_user.id}:profile"
    cached = await db_redis.get(cache_key)
    if cached:
        return json.loads(cached)
    user_data = {"id": current_user.id, "name": current_user.name, "email": current_user.email, "upi_id": current_user.upi_id, "role": current_user.role}
    await db_redis.set(cache_key, json.dumps(user_data), ex=60)
    return user_data

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: int):
    await manager.connect(websocket, user_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)

@app.on_event("startup")
def start_emi_scheduler():
    threading.Thread(target=run_worker, daemon=True).start()


# Mount role-based routers
app.include_router(admin_router)
app.include_router(borrower_router)
app.include_router(lender_router)
app.include_router(user_router)
app.include_router(loan_router)
app.include_router(audit_router)
app.include_router(health_router)
app.include_router(document_router)
app.include_router(repayment_router)
app.include_router(wallet_router)