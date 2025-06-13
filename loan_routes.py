from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload
import schemas
import crud_loan, models
from dependencies import get_db, get_current_user
from audit import log_action
from models import AuditAction, PaymentStatus, PaymentRetryStatus
from notification_service import NotificationService
from loan_search_service import LoanSearchService
from wallet_utils import get_wallet_balance, update_wallet_balance
from datetime import datetime, timedelta
import pytz

IST = pytz.timezone("Asia/Kolkata")

router = APIRouter(prefix="/loans", tags=["loans"])


# ------------------------- LOAN CREATION -------------------------

@router.post("/", response_model=schemas.LoanResponse)
def create_loan(
    loan: schemas.LoanCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if current_user.role not in ["lender", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized to create loans")

    if current_user.role != "admin" and loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Lender ID mismatch")

    db_loan = crud_loan.create_loan(db, loan)
    db.commit()
    db.refresh(db_loan)

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.LOAN_CREATED,
        description=f"Loan #{db_loan.id} created by {current_user.role}",
    )

    NotificationService(db).send_loan_request_notification(db_loan)

    return db_loan


# ------------------------- LIST LOANS -------------------------

@router.get("/", response_model=list[schemas.LoanResponse])
def list_loans(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can view all loans")
    
    loans = crud_loan.get_loans(db)
    return [schemas.LoanResponse.from_orm(loan) for loan in loans]


# ------------------------- UPDATE LOAN STATUS -------------------------

@router.patch("/{loan_id}", response_model=schemas.LoanResponse)
def update_loan_status(
    loan_id: int,
    loan_update: schemas.LoanUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if current_user.role not in ["lender", "admin"]:
        raise HTTPException(status_code=403, detail="Not authorized to update loan status")

    if current_user.role == "lender" and loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this loan")

    if loan_update.status:
        loan = crud_loan.update_loan_status(db, loan_id, loan_update.status)
        NotificationService(db).send_loan_approved_notification(loan) if loan_update.status == "approved" \
            else NotificationService(db).send_loan_rejected_notification(loan)

        if loan_update.status == "active":
            db.commit()
            db.refresh(loan)
# ------- CREATE REPAYMENT SCHEDULE -------
    if loan.status == "active":
        principal = loan.principal_amount
        rate = loan.interest_rate or 0.0
        n = loan.number_of_payments

    # ⏱️ Flexible frequency intervals
    freq_delta = {
        "every_10_seconds": timedelta(seconds=10),
        "every_30_seconds": timedelta(seconds=30),
        "minutely": timedelta(minutes=1),
        "every_5_minutes": timedelta(minutes=5),
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "bi_weekly": timedelta(weeks=2),
        "monthly": timedelta(days=30),
        "quarterly": timedelta(days=90),
        "one_time": timedelta(days=0),
    }.get(loan.payment_frequency.lower(), timedelta(days=30))  # fallback to monthly

    start_date = datetime.now(IST) + freq_delta
    emi_amount = round((principal * (1 + rate / 100)) / n, 2)

    for i in range(n):
        due_date = start_date + freq_delta * i
        payment = models.Payment(
            loan_id=loan.id,
            amount=emi_amount,
            due_date=due_date,
            status=PaymentStatus.pending,
        )
        db.add(payment)

# Optional: Update sub_status
    if loan_update.sub_status is not None:
        loan = crud_loan.update_loan_sub_status(db, loan_id, loan_update.sub_status)

    db.commit()
    db.refresh(loan)
    return loan

# ------------------------- SEARCH LOANS -------------------------

@router.post("/search", response_model=schemas.LoanSearchResponse)
def search_loans(
    filters: schemas.LoanSearchFilters,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return LoanSearchService(db).search_loans(filters=filters, user=current_user)


# ------------------------- MANUAL EMI PAYMENT -------------------------

@router.post("/borrower/pay-emi/{payment_id}", response_model=schemas.PaymentOut)
def pay_emi(payment_id: int, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    payment = db.query(models.Payment).options(joinedload(models.Payment.loan)).filter(models.Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if not payment.loan or payment.loan.borrower_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your loan, homie")

    if payment.status == PaymentStatus.completed:
        raise HTTPException(status_code=400, detail="EMI already paid")

    amount_due = round(payment.amount + payment.late_fee, 2)
    borrower_wallet = get_wallet_balance(current_user.id)

    if borrower_wallet < amount_due:
        retry_log = models.PaymentRetryLog(
            payment_id=payment.id,
            status=PaymentRetryStatus.failed,
            notes="Insufficient funds"
        )
        db.add(retry_log)
        db.commit()
        raise HTTPException(status_code=402, detail="Insufficient funds for mandate")

    payment.status = PaymentStatus.completed
    payment.paid_date = datetime.now(IST)

    update_wallet_balance(current_user.id, -amount_due)
    update_wallet_balance(payment.loan.lender_id, amount_due)

    retry_log = models.PaymentRetryLog(
        payment_id=payment.id,
        status=PaymentRetryStatus.success,
        notes="Mandate successful"
    )
    db.add(retry_log)
    log_action(db, user_id=current_user.id, action=AuditAction.PAYMENT_MADE, payment_id=payment.id)

    db.commit()
    db.refresh(payment)
    return payment


# ------------------------- SIMULATE REPAYMENT (ADMIN TRIGGERED) -------------------------

@router.post("/simulate/repayments")
def simulate_repayments(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can trigger repayments")

    now = datetime.now(IST)

    due_payments = db.query(models.Payment).options(joinedload(models.Payment.loan)).filter(
        models.Payment.due_date <= now,
        models.Payment.status == PaymentStatus.pending
    ).all()

    for payment in due_payments:
        if not payment.loan:
            continue

        borrower_id = payment.loan.borrower_id
        lender_id = payment.loan.lender_id
        amount_due = round(payment.amount + payment.late_fee, 2)
        borrower_wallet = get_wallet_balance(borrower_id)

        if borrower_wallet >= amount_due:
            payment.status = PaymentStatus.completed
            payment.paid_date = now
            update_wallet_balance(borrower_id, -amount_due)
            update_wallet_balance(lender_id, amount_due)
            status_ = PaymentRetryStatus.success
            note = "Auto mandate success"
            log_action(db, user_id=borrower_id, action=AuditAction.PAYMENT_MADE, payment_id=payment.id)
        else:
            status_ = PaymentRetryStatus.failed
            note = "Auto mandate failed: Insufficient funds"
            log_action(db, user_id=borrower_id, action=AuditAction.MANDATE_FAILED, payment_id=payment.id)

        retry_log = models.PaymentRetryLog(
            payment_id=payment.id,
            status=status_,
            notes=note
        )
        db.add(retry_log)

    db.commit()
    return {"message": "Repayments processed"}
