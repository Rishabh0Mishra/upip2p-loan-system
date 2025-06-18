import os
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
import sendgrid
from sendgrid.helpers.mail import Mail
import html
import bleach
import re
from dotenv import load_dotenv
import models
from database import SessionLocal

# ===================== #
# 🔃 Load .env
# ===================== #
load_dotenv()

# ===================== #
# 🔐 JWT Config
# ===================== #
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 30))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7))

# ===================== #
# 📧 SendGrid Config
# ===================== #
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
FROM_EMAIL = os.getenv("FROM_EMAIL")

# ===================== #
# 🔐 Auth Context
# ===================== #
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")

# ===================== #
# 🚫 Token Blacklist
# ===================== #
class TokenBlacklist:
    def __init__(self):
        self.blacklisted_tokens = set()

    def add_token(self, token: str):
        self.blacklisted_tokens.add(token)

    def is_blacklisted(self, token: str) -> bool:
        return token in self.blacklisted_tokens

token_blacklist = TokenBlacklist()

# ===================== #
# 🧼 Input Sanitization
# ===================== #
def sanitize_html_input(text: str) -> str:
    if not text:
        return text
    cleaned = bleach.clean(text, tags=[], strip=True)
    return html.escape(cleaned)

def validate_upi_id(upi_id: str) -> bool:
    upi_pattern = r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z][a-zA-Z0-9.\-_]{2,64}$'
    return bool(re.match(upi_pattern, upi_id))

def validate_password_strength(password: str) -> bool:
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False
    return True

# ===================== #
# 📦 DB Dependency
# ===================== #
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===================== #
# 🔐 Password Hashing
# ===================== #
def get_password_hash(password: str):
    return pwd_context.hash(password)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# ===================== #
# 🔐 User Auth
# ===================== #
def authenticate_user(db: Session, email: str, password: str):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    if not user.email_verification or not user.email_verification.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return user

# ===================== #
# 🔐 Token Creation
# ===================== #
def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(db: Session, user_id: int):
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    token_data = {"user_id": user_id, "exp": expire.isoformat()}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    refresh_token = models.RefreshToken(user_id=user_id, token=token, expires_at=expire)
    db.add(refresh_token)
    db.commit()
    return token

# ===================== #
# 🔐 Token Validator
# ===================== #
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if token_blacklist.is_blacklisted(token):
        raise HTTPException(status_code=401, detail="Token has been revoked")
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        raise credentials_exception
    return user

# ===================== #
# ✅ Role Checker
# ===================== #
def require_roles(allowed_roles: list):
    def role_checker(current_user: models.User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="Operation not permitted")
        return current_user
    return role_checker

# ===================== #
# 📧 Email Sender
# ===================== #
def send_email(to_email: str, subject: str, html_content: str):
    sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )
    try:
        response = sg.send(message)
        return response.status_code
    except Exception as e:
        print("SendGrid Error:", e)
        raise HTTPException(status_code=500, detail="Failed to send email")
