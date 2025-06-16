from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

import models, schemas
from dependencies import get_db, require_roles
import crud_loan
from audit import log_action
from models import AuditAction
from dependencies import get_current_user
from emi_scheduler import create_repayment_schedule  # Make sure this is correct

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
    total_disbursed = sum(loan.principal_amount for loan in loans if loan.status == "active")
    active_loans = sum(1 for loan in loans if loan.status == "active")
    pending_loans = sum(1 for loan in loans if loan.status == "pending")
    completed_loans = sum(1 for loan in loans if loan.status == "completed")
    cancelled_loans = sum(1 for loan in loans if loan.status == "cancelled")

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

@lender_router.get("/loan-requests", response_model=list[schemas.LoanResponse])
def get_pending_loan_requests(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    """Get all pending loan requests for this lender"""
    loans = db.query(models.Loan).filter(
        models.Loan.lender_id == current_user.id,
        models.Loan.status == models.LoanStatus.pending
    ).all()
    return loans

@lender_router.post("/loan-requests/{loan_id}/accept", response_model=schemas.LoanResponse)
def accept_loan_request(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    """Accept a pending loan request, activate it, and create repayment schedule"""
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to respond to this loan")

    if loan.status != models.LoanStatus.pending:
        raise HTTPException(status_code=400, detail="Loan is not in pending status")

    try:
        # Transition to active
        loan = crud_loan.update_loan_status(
            db,
            loan_id,
            models.LoanStatus.active,
            models.LoanSubStatus.none
        )

        # Create EMI schedule
        create_repayment_schedule(db, loan)

        log_action(
            db,
            user_id=current_user.id,
            action=AuditAction.LOAN_STATUS_UPDATED,
            description=f"Loan #{loan.id} accepted by lender and EMI schedule created"
        )

        return loan

    except (SQLAlchemyError, Exception) as e:
        db.rollback()

        # Revert loan status to pending if EMI schedule fails
        crud_loan.update_loan_status(
            db,
            loan_id,
            models.LoanStatus.pending,
            models.LoanSubStatus.none
        )

        raise HTTPException(
            status_code=500,
            detail=f"Loan activation failed: {str(e)}"
        )

@lender_router.post("/loan-requests/{loan_id}/reject", response_model=schemas.LoanResponse)
def reject_loan_request(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    """Reject a pending loan request"""
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to respond to this loan")

    if loan.status != models.LoanStatus.pending:
        raise HTTPException(status_code=400, detail="Loan is not in pending status")

    # Reject the loan - cancel it
    loan = crud_loan.update_loan_status(
        db,
        loan_id,
        models.LoanStatus.cancelled,
        models.LoanSubStatus.none
    )

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.LOAN_STATUS_UPDATED,
        description=f"Loan #{loan.id} rejected by lender"
    )

    return loan

@lender_router.get("/active-loans", response_model=list[schemas.LoanResponse])
def get_active_loans(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    """Get all active loans for this lender"""
    loans = db.query(models.Loan).filter(
        models.Loan.lender_id == current_user.id,
        models.Loan.status == models.LoanStatus.active
    ).all()
    return loans

@lender_router.post("/loans/{loan_id}/mark-completed", response_model=schemas.LoanResponse)
def mark_loan_completed(
    loan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["lender"]))
):
    """Mark an active loan as completed"""
    loan = crud_loan.get_loan(db, loan_id)
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found")

    if loan.lender_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this loan")

    if loan.status != models.LoanStatus.active:
        raise HTTPException(status_code=400, detail="Can only complete active loans")

    loan = crud_loan.update_loan_status(
        db,
        loan_id,
        models.LoanStatus.completed,
        models.LoanSubStatus.none
    )

    log_action(
        db,
        user_id=current_user.id,
        action=AuditAction.LOAN_STATUS_UPDATED,
        description=f"Loan #{loan.id} marked as completed by lender"
    )

    return loan
