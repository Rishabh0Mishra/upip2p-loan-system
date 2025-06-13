from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from dependencies import get_db, require_roles
import models, schemas

audit_router = APIRouter(prefix="/audit", tags=["audit"])

@audit_router.get("/", response_model=List[schemas.AuditLogOut])
def get_audit_logs(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin"]))
):
    return db.query(models.AuditLog).order_by(models.AuditLog.timestamp.desc()).all()
