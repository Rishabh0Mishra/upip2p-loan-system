from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import pytz

from models import (
    Payment, Loan, PaymentStatus, PaymentRetryLog,
    PaymentRetryStatus, AuditAction, LoanStatus, LoanSubStatus
)
from wallet_utils import get_wallet_balance, update_wallet_balance
from audit import log_action
import uuid

IST = pytz.timezone("Asia/Kolkata")


def process_due_emis(db: Session):
    now = datetime.now(IST)

    due_payments = db.query(Payment).options(
        joinedload(Payment.loan)
    ).filter(
        Payment.due_date <= now,
        Payment.status == PaymentStatus.pending
    ).all()

    for payment in due_payments:
        borrower_id = payment.loan.borrower_id
        lender_id = payment.loan.lender_id
        amount_due = round(payment.amount + payment.late_fee, 2)
        borrower_wallet = get_wallet_balance(borrower_id)

        print(f"📆 Processing Payment #{payment.id} | Loan #{payment.loan_id} | Borrower: {borrower_id} | Due: ₹{amount_due} | Wallet: ₹{borrower_wallet}")

        if borrower_wallet >= amount_due:
            # ✅ Mark as paid
            payment.status = PaymentStatus.completed
            payment.paid_date = now
            payment.txn_reference = f"upi-mandate-{uuid.uuid4().hex[:8]}"

            update_wallet_balance(borrower_id, -amount_due)
            update_wallet_balance(lender_id, amount_due)

            retry_log = PaymentRetryLog(
                payment_id=payment.id,
                status=PaymentRetryStatus.success,
                notes="Auto mandate success"
            )
            db.add(retry_log)

            log_action(
                db,
                user_id=borrower_id,
                action=AuditAction.PAYMENT_MADE,
                payment_id=payment.id
            )

            print(f"✅ EMI Payment #{payment.id} completed successfully.")
        else:
            # ❌ Mark failure
            retry_log = PaymentRetryLog(
                payment_id=payment.id,
                status=PaymentRetryStatus.failed,
                notes="Auto mandate failed: Insufficient funds"
            )
            db.add(retry_log)

            log_action(
                db,
                user_id=borrower_id,
                action=AuditAction.MANDATE_FAILED,
                payment_id=payment.id
            )

            print(f"❌ EMI Payment #{payment.id} failed due to insufficient funds.")

    db.commit()

    # 🔁 Auto-complete eligible loans
    complete_paid_loans(db)


def complete_paid_loans(db: Session):
    """Mark loans as completed if all their payments are paid"""
    active_loans = db.query(Loan).filter(Loan.status == LoanStatus.active).all()

    for loan in active_loans:
        total_payments = db.query(Payment).filter(Payment.loan_id == loan.id).count()
        completed_payments = db.query(Payment).filter(
            Payment.loan_id == loan.id,
            Payment.status == PaymentStatus.completed
        ).count()

        if total_payments > 0 and total_payments == completed_payments:
            loan.status = LoanStatus.completed
            loan.sub_status = LoanSubStatus.none
            log_action(
                db,
                user_id=loan.lender_id,
                action=AuditAction.LOAN_STATUS_UPDATED,
                loan_id=loan.id,
                description=f"Loan #{loan.id} marked as completed after all EMIs paid"
            )
            print(f"✅ Loan #{loan.id} marked as COMPLETED.")
    
    db.commit()
