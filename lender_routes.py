from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from decimal import Decimal

import models, schemas
from dependencies import get_db, require_roles, get_current_user
import crud_loan
from audit import log_action
from emi_scheduler import create_repayment_schedule
from exceptions import InsufficientFundsException
from models import AuditAction, LoanStatus, LoanSubStatus

lender_router = APIRouter(prefix="/lender", tags=["lender"])


@lender_router.get("/dashboard")
def lender_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    if current_user.role != "lender":
        raise HTTPException(status_code=403, detail="Only lenders can access this dashboard.")

    loans = db.query(models.Loan).filter(models.Loan.lender_id == current_user.id).all()

    total_loans = len(loans)
    total_disbursed = sum(loan.principal_amount for loan in loans if loan.status == LoanStatus.active)
    active_loans = sum(1 for loan in loans if loan.status == LoanStatus.active)
    pending_loans = sum(1 for loan in loans if loan.status == LoanStatus.pending)
    completed_loans = sum(1 for loan in loans if loan.status == LoanStatus.completed)
    cancelled_loans = sum(1 for loan in loans if loan.status == LoanStatus.cancelled)

    avg_interest = round(
        sum(loan.interest_rate for loan in loans if loan.interest_rate is not None) / total_loans,
        2
    ) if total_loans > 0 else 0

    return {
        "total_loans": total_loans,
        "total_disbursed": float(total_disbursed),
        "active_loans": active_loans,
        "pending_loans": pending_loans,
        "completed_loans": completed_loans,
        "cancelled_loans": cancelled_loans,
        "average_interest_rate": avg_interest
    }


@lender_router.get("/loan-requests", response_model=list[schemas.LenderLoanRequestOut])
def get_pending_loan_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    loans = db.query(models.Loan).filter(
        models.Loan.lender_id == current_user.id,
        models.Loan.status == LoanStatus.pending
    ).all()

    enriched = []
    for loan in loans:
        borrower = db.query(models.User).filter(models.User.id == loan.borrower_id).first()

        borrower_name = borrower.name if borrower and borrower.name else f"User#{loan.borrower_id}"
        risk_score = int(round(borrower.risk_score)) if borrower and borrower.risk_score is not None else 50
        reason = loan.reason if hasattr(loan, "reason") and loan.reason else "General purpose"

        enriched.append({
            "id": loan.id,
            "borrower_name": borrower_name,
            "amount": float(loan.principal_amount),
            "duration_months": loan.number_of_payments,
            "risk_score": risk_score,
            "reason": reason
        })

    return enriched





@lender_router.post("/loan-requests/{loan_id}/accept", response_model=schemas.LoanResponse)
def accept_loan_request(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to accept this loan")

    if loan.status != LoanStatus.pending:
        raise HTTPException(status_code=400, detail="Loan is not in pending status")

    lender_wallet = crud_loan.get_wallet(db, current_user.id)
    principal = loan.principal_amount

    if lender_wallet.balance < principal:
        raise InsufficientFundsException("Insufficient balance to accept this loan.")

    try:
        lender_wallet.balance -= principal
        db.commit()

        rate = loan.interest_rate
        n = loan.number_of_payments
        time_years = Decimal(n) / Decimal("12")

        total_amount = principal + (principal * rate * time_years)
        payment_amount = total_amount / Decimal(n)

        loan.total_amount = total_amount.quantize(Decimal("0.01"))
        loan.payment_amount = payment_amount.quantize(Decimal("0.01"))
        loan.status = LoanStatus.active
        loan.sub_status = LoanSubStatus.none

        db.commit()
        db.refresh(loan)

        create_repayment_schedule(db, loan)

        log_action(
            db=db,
            user_id=current_user.id,
            action=AuditAction.LOAN_STATUS_UPDATED,
            description={
                "loan_id": loan.id,
                "action": "Loan accepted",
                "new_lender_balance": str(lender_wallet.balance)
            },
            loan_id=loan.id
        )

        return loan

    except (SQLAlchemyError, Exception) as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Loan activation failed: {str(e)}")


@lender_router.post("/loan-requests/{loan_id}/reject", response_model=schemas.LoanResponse)
def reject_loan_request(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to respond to this loan")

    if loan.status != LoanStatus.pending:
        raise HTTPException(status_code=400, detail="Loan is not in pending status")

    loan = crud_loan.update_loan_status(
        db,
        loan_id,
        LoanStatus.cancelled,
        LoanSubStatus.none
    )

    log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.LOAN_STATUS_UPDATED,
        description=f"Loan #{loan.id} rejected by lender",
        loan_id=loan.id
    )

    return loan


@lender_router.get("/active-loans", response_model=list[schemas.LoanResponse])
def get_active_loans(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    loans = db.query(models.Loan).filter(
        models.Loan.lender_id == current_user.id,
        models.Loan.status == LoanStatus.active
    ).all()
    return loans


@lender_router.post("/loans/{loan_id}/mark-completed")
def mark_loan_completed(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this loan")

    if loan.status != LoanStatus.active:
        raise HTTPException(status_code=400, detail="Can only complete active loans")

    loan = crud_loan.update_loan_status(
        db,
        loan_id,
        LoanStatus.completed,
        LoanSubStatus.none
    )

    lender_wallet = crud_loan.get_wallet(db, current_user.id)
    borrower_wallet = crud_loan.get_wallet(db, loan.borrower_id)

    log_action(
        db=db,
        user_id=current_user.id,
        action=AuditAction.LOAN_STATUS_UPDATED,
        description=f"Loan #{loan.id} marked as completed by lender",
        loan_id=loan.id
    )

    return {
        "loan": loan,
        "lender_wallet_balance": float(lender_wallet.balance),
        "borrower_wallet_balance": float(borrower_wallet.balance)
    }
