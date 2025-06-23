from sqlalchemy.orm import Session
from typing import Optional, Union
from models import AuditLog, AuditAction


def log_action(
    db: Session,
    user_id: int,
    action: AuditAction,
    description: Optional[Union[str, dict]] = None,
    payment_id: Optional[int] = None,
    loan_id: Optional[int] = None
):
    try:
        if isinstance(description, dict):
            description = str(description)

        log = AuditLog(
            user_id=user_id,
            action=action,
            description=description,
            payment_id=payment_id,
            loan_id=loan_id
        )
        db.add(log)
        db.commit()
    except Exception as e:
        db.rollback()
        raise
