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
from models import Loan, Payment, User, PaymentStatus
from schemas import PaymentOut
from typing import List


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

    try:
        db_loan = crud_loan.create_loan(db=db, loan=loan, current_user=current_user)
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
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Loan creation failed: {str(e)}")


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


@router.patch("/{loan_id}", response_model=schemas.LoanResponse)
def update_loan_status(
    loan_id: int,
    loan_update: schemas.LoanUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    try:
        loan = crud_loan.get_loan(db, loan_id)
        if not loan:
            raise HTTPException(status_code=404, detail="Loan not found")

        if current_user.role not in ["lender", "admin"]:
            raise HTTPException(status_code=403, detail="Not authorized to update loan status")

        if current_user.role == "lender" and loan.lender_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this loan")

        if loan_update.status:
            # 💰 If activating loan, transfer funds from lender to borrower
            if loan_update.status == "active":
                lender_balance = get_wallet_balance(db, loan.lender_id)
                if lender_balance < loan.principal_amount:
                    raise HTTPException(
                        status_code=400,
                        detail="Lender has insufficient funds to activate the loan"
                    )

                update_wallet_balance(db, loan.lender_id, -loan.principal_amount)
                update_wallet_balance(db, loan.borrower_id, loan.principal_amount)

                log_action(
                    db,
                    user_id=loan.lender_id,
                    action=AuditAction.WALLET_DEBITED,
                    description=f"₹{loan.principal_amount} transferred from lender #{loan.lender_id} to borrower #{loan.borrower_id} for Loan #{loan.id}"
                )

            # ✅ Update status
            loan = crud_loan.update_loan_status(db, loan_id, loan_update.status)

            # 🔔 Send appropriate notifications
            if loan_update.status == "approved":
                NotificationService(db).send_loan_approved_notification(loan)

                # 🔐 Initiate dual NSDL eSign flow after approval
                try:
                    success, msg, signing_url = crud_loan.initiate_dual_signing_for_loan(db, loan)
                    if not success:
                        raise HTTPException(status_code=500, detail=f"Dual signing initiation failed: {msg}")

                    loan.sub_status = models.LoanSubStatus.borrower_pending_signature
                    log_action(
                        db=db,
                        user_id=loan.borrower_id,
                        action=AuditAction.DOCUMENT_GENERATED,
                        loan_id=loan.id,
                        description=f"eSign initiated for borrower on Loan #{loan.id}"
                    )
                except Exception as e:
                    db.rollback()
                    raise HTTPException(status_code=500, detail=f"Failed to initiate signing: {str(e)}")

            elif loan_update.status == "rejected":
                NotificationService(db).send_loan_rejected_notification(loan)

            # 💾 Refresh loan state after activation
            if loan_update.status == "active":
                db.commit()
                db.refresh(loan)

        # 🧾 Create EMI schedule only once (on activation)
        if loan.status == "active":
            existing_payments = db.query(models.Payment).filter(models.Payment.loan_id == loan.id).count()
            if existing_payments == 0:
                principal = loan.principal_amount
                rate = loan.interest_rate or 0.0
                n = loan.number_of_payments

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
                }.get(loan.payment_frequency.lower(), timedelta(days=30))

                start_date = datetime.now(IST) + freq_delta
                emi_amount = round((principal * (1 + rate / 100)) / n, 2)

                for i in range(n):
                    due_date = start_date + freq_delta * i
                    payment = models.Payment(
                        loan_id=loan.id,
                        amount=emi_amount,
                        due_date=due_date,
                        status=PaymentStatus.pending,
                        emi_number=i + 1
                    )
                    db.add(payment)

        # 🔄 Optional substatus update (if explicitly sent)
        if loan_update.sub_status is not None:
            loan = crud_loan.update_loan_sub_status(db, loan_id, loan_update.sub_status)

        db.commit()
        db.refresh(loan)
        return loan

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Loan update failed: {str(e)}")



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
def pay_emi(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Borrower manually pays the next pending EMI from wallet.
    """
    try:
        # 🔒 Step 1: Auth & Validation
        payment = (
            db.query(models.Payment)
            .options(joinedload(models.Payment.loan))
            .filter(models.Payment.id == payment_id)
            .first()
        )
        if not payment:
            raise HTTPException(status_code=404, detail={"detail": "Payment not found", "code": "payment_not_found"})
        
        if not payment.loan:
            raise HTTPException(status_code=404, detail={"detail": "Associated loan not found", "code": "loan_not_found"})

        if payment.loan.borrower_id != current_user.id:
            raise HTTPException(status_code=403, detail={"detail": "You are not the borrower for this loan", "code": "unauthorized_user"})

        if payment.status == PaymentStatus.completed:
            raise HTTPException(status_code=400, detail={"detail": "EMI already paid", "code": "already_paid"})

        # 🔁 Step 2: Enforce sequential EMI payments
        next_emi = (
            db.query(models.Payment)
            .filter(models.Payment.loan_id == payment.loan_id, models.Payment.status == PaymentStatus.pending)
            .order_by(models.Payment.emi_number.asc())
            .first()
        )
        if not next_emi:
            raise HTTPException(status_code=400, detail={"detail": "No pending EMIs for this loan", "code": "no_pending_emi"})
        
        if payment.id != next_emi.id:
            raise HTTPException(status_code=400, detail={
                "detail": "You must pay EMIs in order. This is not the next pending EMI.",
                "code": "invalid_payment_order"
            })

        # 💰 Step 3: Wallet & Amount check
        amount_due = round(payment.amount + (payment.late_fee or 0), 2)
        borrower_wallet = get_wallet_balance(db, current_user.id)

        if borrower_wallet < amount_due:
            db.add(models.PaymentRetryLog(
                payment_id=payment.id,
                status=PaymentRetryStatus.failed,
                notes=f"Manual payment failed: Insufficient funds. Required: {amount_due}, Available: {borrower_wallet}"
            ))
            log_action(db, user_id=current_user.id, action=AuditAction.MANDATE_FAILED, payment_id=payment.id)
            db.commit()
            raise HTTPException(status_code=402, detail={
                "detail": f"Insufficient funds. Required ₹{amount_due}, Available ₹{borrower_wallet}",
                "code": "insufficient_funds"
            })

        # ✅ Step 4: Deduct & Mark as Paid
        update_wallet_balance(db, current_user.id, -amount_due)
        update_wallet_balance(db, payment.loan.lender_id, amount_due)

        payment.status = PaymentStatus.completed
        payment.paid_date = datetime.now(IST)
        payment.txn_reference = f"MAN_{payment.loan_id}_{payment.id}_{int(datetime.now().timestamp())}"

        db.add(models.PaymentRetryLog(
            payment_id=payment.id,
            status=PaymentRetryStatus.success,
            notes=f"Manual EMI paid successfully. Amount ₹{amount_due}"
        ))
        log_action(db, user_id=current_user.id, action=AuditAction.PAYMENT_MADE, payment_id=payment.id,
                    description=f"Paid EMI #{payment.emi_number} for Loan #{payment.loan_id}: ₹{amount_due}")
        
        db.commit()
        db.refresh(payment)
        return payment

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail={
            "detail": f"Unexpected error during EMI payment: {str(e)}",
            "code": "internal_server_error"
        })

# ------------------------- SIMULATE REPAYMENT (ADMIN TRIGGERED) -------------------------

@router.post("/simulate/repayments")
def simulate_repayments(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can trigger repayments")

    try:
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

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Simulation failed: {str(e)}")

# ------------------------- GET NEXT LOAN DETAILS -------------------------

@router.get("/{loan_id}/emis", response_model=List[PaymentOut])
def get_emis_for_loan(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify loan exists and belongs to the user (either borrower or lender)
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if current_user.id not in [loan.borrower_id, loan.lender_id] and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Not authorized to view this loan")

    # Return all EMI records ordered by EMI number
    emis = (
        db.query(Payment)
        .filter(Payment.loan_id == loan_id)
        .order_by(Payment.emi_number)
        .all()
    )
    return emis