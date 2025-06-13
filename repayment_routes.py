# repayment_routes.py
from fastapi import APIRouter

router = APIRouter(prefix="/borrower", tags=["repayment"])


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime
import random

from dependencies import get_db, require_roles
from audit import log_action
from models import AuditAction, PaymentRetryLog, PaymentRetryStatus, User, Wallet, Payment, Loan

repayment_router = APIRouter(prefix="/borrower", tags=["repayment"])


@repayment_router.post("/pay-emi/{payment_id}")
def pay_emi(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["borrower"]))
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    loan = db.query(Loan).filter(Loan.id == payment.loan_id).first()
    if not loan or loan.borrower_id != current_user.id:
        raise HTTPException(status_code=403, detail="You are not authorized to pay this EMI")

    if payment.status == "paid":
        raise HTTPException(status_code=400, detail="EMI already paid")

    borrower_wallet = db.query(Wallet).filter(Wallet.user_id == current_user.id).first()
    if not borrower_wallet:
        raise HTTPException(status_code=404, detail="Borrower wallet not found")

    if borrower_wallet.balance < float(payment.amount):
        retry_log = PaymentRetryLog(
            payment_id=payment.id,
            status=PaymentRetryStatus.failed,
            notes="Insufficient wallet balance"
        )
        db.add(retry_log)
        db.commit()
        raise HTTPException(status_code=400, detail="Insufficient wallet balance")

    is_success = random.random() < 0.8  # 80% UPI success simulation

    if is_success:
        borrower_wallet.balance -= float(payment.amount)
        payment.status = "paid"
        payment.paid_date = datetime.now()
        status = PaymentRetryStatus.success
        notes = "Payment successful via UPI mandate simulation"
    else:
        payment.status = "failed"
        status = PaymentRetryStatus.failed
        notes = "UPI mandate simulation failed"

    retry_log = PaymentRetryLog(
        payment_id=payment.id,
        status=status,
        notes=notes
    )

    db.add(retry_log)
    db.commit()

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.EMI_PAYMENT_ATTEMPTED,
        description=f"Payment ID {payment_id} - Status: {status.value}"
    )

    return {
        "success": is_success,
        "payment_status": payment.status
    }
