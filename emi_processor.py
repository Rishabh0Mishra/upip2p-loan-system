from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from datetime import datetime
from decimal import Decimal
import pytz
import uuid

from models import (
    Payment, Loan, PaymentStatus, PaymentRetryLog,
    PaymentRetryStatus, AuditAction, LoanStatus, LoanSubStatus
)
from wallet_utils import get_wallet_balance, update_wallet_balance
from audit import log_action

IST = pytz.timezone("Asia/Kolkata")


def process_due_emis(db: Session):
    now = datetime.now(IST)
    print(f"🕐 EMI Processor running at: {now.strftime('%H:%M:%S.%f')[:-3]}")

    # Get ONLY the next due EMI for each loan
    subquery = (
        db.query(
            Payment.loan_id,
            func.min(Payment.due_date).label("next_due")
        )
        .filter(
            Payment.status == PaymentStatus.pending,
            Payment.due_date <= now
        )
        .group_by(Payment.loan_id)
        .subquery()
    )

    due_payments = db.query(Payment).options(
        joinedload(Payment.loan)
    ).join(
        subquery,
        (Payment.loan_id == subquery.c.loan_id) &
        (Payment.due_date == subquery.c.next_due)
    ).all()

    print(f"📊 Found {len(due_payments)} EMIs ready for processing")

    for payment in due_payments:
        borrower_id = payment.loan.borrower_id
        lender_id = payment.loan.lender_id

        # Ensure Decimals
        amount_due = (Decimal(payment.amount) + Decimal(payment.late_fee)).quantize(Decimal('0.01'))

        if payment.due_date.tzinfo is None:
            payment.due_date = IST.localize(payment.due_date)

        time_overdue = (now - payment.due_date).total_seconds()
        print(f"📆 Processing EMI #{payment.emi_number} | Loan #{payment.loan_id}")
        print(f"    Due: {payment.due_date.strftime('%H:%M:%S.%f')[:-3]} | Overdue by: {time_overdue:.1f}s")
        print(f"    Borrower: {borrower_id} | Amount: ₹{amount_due}")

        borrower_wallet = Decimal(get_wallet_balance(db, borrower_id))
        print(f"    Wallet Balance: ₹{borrower_wallet}")

        if borrower_wallet >= amount_due:
            payment.status = PaymentStatus.completed
            payment.paid_date = now
            payment.txn_reference = f"upi-mandate-{uuid.uuid4().hex[:8]}"

            update_wallet_balance(db, borrower_id, -amount_due)
            update_wallet_balance(db, lender_id, amount_due)

            db.add(PaymentRetryLog(
                payment_id=payment.id,
                status=PaymentRetryStatus.success,
                notes="Auto mandate success"
            ))

            log_action(
                db,
                user_id=borrower_id,
                action=AuditAction.PAYMENT_MADE,
                payment_id=payment.id,
                loan_id=payment.loan_id
            )

            print(f"✅ EMI #{payment.emi_number} for Loan #{payment.loan_id} completed successfully")
        else:
            shortage = (amount_due - borrower_wallet).quantize(Decimal('0.01'))

            db.add(PaymentRetryLog(
                payment_id=payment.id,
                status=PaymentRetryStatus.failed,
                notes=f"Auto mandate failed: Insufficient funds (short by ₹{shortage})"
            ))

            log_action(
                db,
                user_id=borrower_id,
                action=AuditAction.MANDATE_FAILED,
                payment_id=payment.id,
                loan_id=payment.loan_id
            )

            print(f"❌ EMI #{payment.emi_number} for Loan #{payment.loan_id} failed - short by ₹{shortage}")

    if due_payments:
        db.commit()
        print(f"💾 Committed {len(due_payments)} EMI transactions")
        complete_paid_loans(db)
    else:
        print("😴 No EMIs due for processing")


def complete_paid_loans(db: Session):
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
            print(f"🎉 Loan #{loan.id} marked as COMPLETED - all EMIs paid!")

    db.commit()
