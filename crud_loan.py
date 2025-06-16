from sqlalchemy.orm import Session, joinedload
from decimal import Decimal
from fastapi import HTTPException
import models
import schemas
from config import settings

from cache import cache_result, invalidate_cache


def validate_loan_data(loan: schemas.LoanCreate):
    if loan.principal_amount < settings.min_loan_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Loan amount must be at least ₹{settings.min_loan_amount}"
        )
    if loan.principal_amount > settings.max_loan_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Loan amount cannot exceed ₹{settings.max_loan_amount}"
        )
    if loan.lender_id == loan.borrower_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot create a loan to yourself"
        )


def validate_users_exist(db: Session, lender_id: int, borrower_id: int):
    lender = db.query(models.User).filter(models.User.id == lender_id).first()
    borrower = db.query(models.User).filter(models.User.id == borrower_id).first()
    if not lender:
        raise HTTPException(status_code=404, detail="Lender not found")
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return lender, borrower


def create_loan(db: Session, loan: schemas.LoanCreate):
    validate_loan_data(loan)
    lender, borrower = validate_users_exist(db, loan.lender_id, loan.borrower_id)

    db_loan = models.Loan(
        lender_id=loan.lender_id,
        borrower_id=loan.borrower_id,
        principal_amount=Decimal(str(loan.principal_amount)),
        interest_rate=Decimal(str(loan.interest_rate)),
        payment_frequency=loan.payment_frequency,
        number_of_payments=loan.number_of_payments,
        payment_amount=Decimal(str(loan.payment_amount)),
        total_amount=Decimal(str(loan.total_amount)),
        description=loan.description,
        start_date=loan.start_date,
        due_date=loan.due_date,
        status=models.LoanStatus.pending,
        sub_status=models.LoanSubStatus.none
    )

    db.add(db_loan)
    db.commit()
    db.refresh(db_loan)

    # 🔥 Invalidate both lender and borrower cache entries
    invalidate_cache(f"get_loans_by_user:{loan.lender_id}")
    invalidate_cache(f"get_loans_by_user:{loan.borrower_id}")

    return db_loan


@cache_result(expiration=1800)
def get_loan_with_details(db: Session, loan_id: int):
    return db.query(models.Loan)\
        .options(
            joinedload(models.Loan.lender),
            joinedload(models.Loan.borrower),
            joinedload(models.Loan.payments)
        )\
        .filter(models.Loan.id == loan_id)\
        .first()


def get_loan(db: Session, loan_id: int):
    return db.query(models.Loan).filter(models.Loan.id == loan_id).first()


def paginate_query(query, page: int = 1, page_size: int = 20):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


def get_loans(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Loan).offset(skip).limit(limit).all()


@cache_result(expiration=1800)
def get_loans_by_user(db: Session, user_id: int):
    return db.query(models.Loan)\
        .options(joinedload(models.Loan.payments))\
        .filter(
            (models.Loan.lender_id == user_id) |
            (models.Loan.borrower_id == user_id)
        ).all()


def can_transition_status(current_status: models.LoanStatus, new_status: models.LoanStatus) -> bool:
    valid_transitions = {
        models.LoanStatus.pending: [models.LoanStatus.active, models.LoanStatus.cancelled],
        models.LoanStatus.active: [models.LoanStatus.completed, models.LoanStatus.cancelled],
        models.LoanStatus.completed: [],
        models.LoanStatus.cancelled: []
    }
    return new_status in valid_transitions.get(current_status, [])


def update_loan_status(db: Session, loan_id: int, new_status: models.LoanStatus, new_sub_status: models.LoanSubStatus = models.LoanSubStatus.none):
    loan = get_loan(db, loan_id)
    if not loan:
        return None

    if not can_transition_status(loan.status, new_status):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {loan.status.value} to {new_status.value}"
        )

    loan.status = new_status
    loan.sub_status = new_sub_status
    db.commit()
    db.refresh(loan)

    # 🔥 Invalidate both lender and borrower cache entries
    invalidate_cache(f"get_loans_by_user:{loan.lender_id}")
    invalidate_cache(f"get_loans_by_user:{loan.borrower_id}")

    return loan


def delete_loan(db: Session, loan_id: int):
    loan = get_loan(db, loan_id)
    if loan:
        if loan.status != models.LoanStatus.pending:
            raise HTTPException(
                status_code=400,
                detail="Can only delete pending loans"
            )
        db.delete(loan)
        db.commit()
    return loan


def update_loan_sub_status(db: Session, loan_id: int, sub_status: schemas.LoanSubStatus):
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    if not loan:
        return None
    loan.sub_status = sub_status
    db.commit()
    db.refresh(loan)
    return loan
