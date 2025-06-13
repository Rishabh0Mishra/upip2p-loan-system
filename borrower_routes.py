# borrower_routes.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import models, schemas, crud_loan
from dependencies import get_db, require_roles
from audit import log_action
from models import AuditAction

borrower_router = APIRouter(prefix="/borrower", tags=["borrower"])


# ----------- DASHBOARD -----------

@borrower_router.get("/dashboard", response_model=list[schemas.LoanResponse])
def borrower_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_roles(["borrower"]))
):
    loans = crud_loan.get_loans_by_user(db, current_user.id)
    return [schemas.LoanResponse(**loan.__dict__) for loan in loans]


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
