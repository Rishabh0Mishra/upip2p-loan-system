import secrets
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from models import RefreshToken
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_refresh_token(db: Session, user_id: int):
    token = secrets.token_urlsafe(32)  # secure random string
    expires = datetime.utcnow() + timedelta(days=7)
    db_token = RefreshToken(user_id=user_id, token=token, expires_at=expires)
    db.add(db_token)
    db.commit()
    db.refresh(db_token)
    return db_token.token