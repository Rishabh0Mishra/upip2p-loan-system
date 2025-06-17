from sqlalchemy.orm import Session
from decimal import Decimal
import models

from logging_config import StructuredLogger

logger = StructuredLogger("wallet_logger")

def get_wallet_balance(db: Session, user_id: int) -> Decimal:
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()
    balance = wallet.balance if wallet else Decimal("0.00")

    logger.log_event("wallet_balance_checked", {
        "user_id": user_id,
        "balance": float(balance)
    })

    return balance

def update_wallet_balance(db: Session, user_id: int, amount: float) -> models.Wallet:
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()

    if not wallet:
        wallet = models.Wallet(user_id=user_id, balance=Decimal("0.00"))
        db.add(wallet)

    old_balance = float(wallet.balance)
    wallet.balance += Decimal(str(amount))
    db.commit()
    db.refresh(wallet)

    logger.log_event("wallet_balance_updated", {
        "user_id": user_id,
        "amount_changed": float(amount),
        "old_balance": old_balance,
        "new_balance": float(wallet.balance)
    })

    return wallet
