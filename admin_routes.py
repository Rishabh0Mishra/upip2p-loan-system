from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

import models, schemas
from dependencies import get_db, require_roles
from audit import log_action
from models import AuditAction

admin_router = APIRouter(prefix="/admin", tags=["admin"])

@admin_router.get("/admin-only")
def admin_panel(current_user: models.User = Depends(require_roles(["admin"]))):
    return {"msg": f"Hello Admin {current_user.name}"}

@admin_router.get("/users", response_model=List[schemas.UserOut])
def get_all_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin"])) # current_user is used for access control
):
    users = db.query(models.User).filter(models.User.deleted_at.is_(None)).all()
    return users


@admin_router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin"]))
):
    try:
        user = db.query(models.User).filter(models.User.id == user_id, models.User.deleted_at == None).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.deleted_at = datetime.utcnow()
        db.commit()
        return {"msg": f"User with id {user_id} soft-deleted."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")


@admin_router.put("/users/{user_id}/role")
def change_user_role(
    user_id: int,
    role_update: schemas.RoleUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["admin"]))
):
    try:
        user = db.query(models.User).filter(models.User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if user.role == "admin":
            raise HTTPException(status_code=403, detail="Cannot change role of another admin")

        user.role = role_update.new_role
        db.commit()
        db.refresh(user)

        log_action(
            db,
            user_id=current_user.id,
            action=AuditAction.ROLE_CHANGED,
            description=f"Changed role of user {user_id} to {role_update.new_role}"
        )

        return {"msg": f"User role updated to {role_update.new_role}"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
