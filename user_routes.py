from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dependencies import get_db, get_current_user, send_email
from passlib.context import CryptContext
import schemas, models
import uuid
from audit import log_action
from models import AuditAction

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

user_router = APIRouter(prefix="/user", tags=["user"])


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)


def hash_password(password):
    return pwd_context.hash(password)


@user_router.post("/update-profile")
def update_profile(
    update_data: schemas.UpdateProfile,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not verify_password(update_data.password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect password")

    updated_fields = []
    if update_data.name and update_data.name != current_user.name:
        current_user.name = update_data.name
        updated_fields.append("name")
    if update_data.upi_id and update_data.upi_id != current_user.upi_id:
        current_user.upi_id = update_data.upi_id
        updated_fields.append("upi_id")
        # TODO: flag for mandate re-authorization or UPI PIN reset

    db.commit()
    db.refresh(current_user)

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.PROFILE_UPDATED,
        description=f"Updated fields: {', '.join(updated_fields)}"
    )

    return {"msg": "Profile updated", "user": {"name": current_user.name, "upi_id": current_user.upi_id}}


@user_router.post("/change-password")
def change_password(
    body: schemas.ChangePassword,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect current password")

    current_user.hashed_password = hash_password(body.new_password)
    db.commit()

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.PASSWORD_CHANGED,
        description="User changed their password"
    )

    return {"msg": "Password changed successfully"}


@user_router.post("/request-verification")
def request_email_verification(
    body: schemas.EmailVerificationRequest,
    db: Session = Depends(get_db)
):
    user = db.query(models.User).filter(models.User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    token = str(uuid.uuid4())
    existing = db.query(models.EmailVerificationToken).filter_by(user_id=user.id).first()
    if existing:
        existing.token = token
        existing.is_verified = False
    else:
        db.add(models.EmailVerificationToken(user_id=user.id, token=token))

    db.commit()

    verification_link = f"http://localhost:8000/user/verify-email?token={token}"
    send_email(
        to_email=user.email,
        subject="Verify your email",
        html_content=f"<p>Click <a href='{verification_link}'>here</a> to verify your email.</p>"
    )

    return {"msg": "Verification email sent"}


@user_router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    token_entry = db.query(models.EmailVerificationToken).filter_by(token=token).first()
    if not token_entry:
        raise HTTPException(status_code=404, detail="Invalid or expired token")

    if token_entry.is_verified:
        return {"msg": "Email already verified"}

    token_entry.is_verified = True

    user = db.query(models.User).filter(models.User.id == token_entry.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_verified = True

    db.commit()
    db.refresh(user)

    log_action(
        db,
        user_id=token_entry.user_id,
        action=AuditAction.EMAIL_VERIFIED,
        description="User verified their email"
    )

    return {"msg": "Email verified successfully", "verified": user.is_verified}

