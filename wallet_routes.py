from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from dependencies import get_db, get_current_user
from wallet_utils import get_wallet_balance, update_wallet_balance
import models, schemas
from audit import log_action
from models import AuditAction

wallet_router = APIRouter(prefix="/wallet", tags=["wallet"])

@wallet_router.get("/balance")
def get_balance(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    balance = get_wallet_balance(db, current_user.id)  # ✅ Corrected argument order
    return {"user_id": current_user.id, "balance": round(balance, 2)}

@wallet_router.post("/add-funds")
def add_funds(
    payload: schemas.WalletTopUpRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if payload.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")

    wallet = update_wallet_balance(db, current_user.id, payload.amount)  # ✅ Corrected argument order

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.WALLET_TOPUP,
        description=f"Wallet topped up by ₹{payload.amount}"
    )

    return {
        "message": f"₹{payload.amount} added to your wallet.",
        "new_balance": round(wallet.balance, 2)
    }
