# wallet_utils.py

from sqlalchemy.orm import Session
from decimal import Decimal
import models

def get_wallet_balance(user_id: int, db: Session) -> float:
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()
    if not wallet:
        return 0.0
    return round(wallet.balance, 2)

def update_wallet_balance(user_id: int, amount: float, db: Session):
    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()
    
    if not wallet:
        wallet = models.Wallet(user_id=user_id, balance=Decimal("0.00"))
        db.add(wallet)
        db.flush()  # Ensure wallet.id is available if needed

    wallet.balance += Decimal(str(amount))  # Ensures safe conversion
    db.commit()
    db.refresh(wallet)

    print(f"[Wallet] User {user_id} balance updated: {amount:+} → New: ₹{wallet.balance}")
    
    return wallet