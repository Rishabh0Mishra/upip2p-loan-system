# borrower_routes.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud_loan
from dependencies import get_db, require_roles
from audit import log_action
from models import AuditAction
from decimal import Decimal

borrower_router = APIRouter(prefix="/borrower", tags=["borrower"])


# ----------- DASHBOARD -----------

@borrower_router.get("/dashboard", response_model=schemas.BorrowerDashboard)
def borrower_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["borrower"]))
):
    loans = crud_loan.get_loans_by_user(db, current_user.id)

    active_loans = [loan for loan in loans if loan.status == models.LoanStatus.active]
    pending_requests = [loan for loan in loans if loan.status == models.LoanStatus.pending]
    completed_loans = [loan for loan in loans if loan.status == models.LoanStatus.completed]

    total_borrowed = sum(
        [loan.principal_amount for loan in loans if loan.status in [models.LoanStatus.active, models.LoanStatus.completed]],
        Decimal("0.00")
    )

    total_repaid = Decimal("0.00")
    for loan in loans:
        if loan.status in [models.LoanStatus.active, models.LoanStatus.completed]:
            for payment in loan.payments:
                if payment.status == models.PaymentStatus.completed:
                    total_repaid += Decimal(str(payment.amount)) + Decimal(str(payment.late_fee or 0))

    next_due = (
        db.query(models.Payment)
        .join(models.Loan)
        .filter(models.Loan.borrower_id == current_user.id)
        .filter(models.Payment.status == models.PaymentStatus.pending)
        .order_by(models.Payment.due_date.asc())
        .first()
    )

    wallet = db.query(models.Wallet).filter(models.Wallet.user_id == current_user.id).first()
    wallet_balance = wallet.balance if wallet else Decimal("0.00")

    def loan_to_response(loan: models.Loan):
        return schemas.LoanResponse(
            id=loan.id,
            borrower_id=loan.borrower_id,
            lender_id=loan.lender_id,
            principal_amount=loan.principal_amount,
            interest_rate=loan.interest_rate,
            payment_frequency=loan.payment_frequency,
            number_of_payments=loan.number_of_payments,
            status=loan.status,
            created_at=loan.created_at,
            updated_at=loan.updated_at,
        )

    return schemas.BorrowerDashboard(
        active_loans=[loan_to_response(loan) for loan in active_loans],
        pending_requests=[loan_to_response(loan) for loan in pending_requests],
        completed_loans_count=len(completed_loans),
        total_borrowed=total_borrowed,
        total_repaid=total_repaid,
        next_payment_due=schemas.PaymentResponse.model_validate(next_due, from_attributes=True) if next_due else None,
        wallet_balance=wallet_balance
    )


# ----------- REQUEST LOAN -----------

@borrower_router.post("/request-loan", response_model=schemas.LoanResponse)
def request_loan(
    loan: schemas.LoanCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["borrower"]))
):
    if loan.borrower_id != current_user.id:
        raise HTTPException(status_code=403, detail="You can only request loans for yourself")

    db_loan = crud_loan.create_loan(db, loan)

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.LOAN_CREATED,
        description=f"Loan request #{db_loan.id} created by borrower"
    )

    return db_loan
