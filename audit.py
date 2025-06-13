from sqlalchemy.orm import Session
from models import AuditLog, AuditAction

def log_action(db: Session, user_id: int, action: AuditAction, description: str = None,payment_id: int = None, loan_id: int = None):
    log = AuditLog(user_id=user_id, action=action, description=description, payment_id=payment_id, loan_id=loan_id)
    db.add(log)
    db.commit()
