from sqlalchemy.orm import Session, joinedload
from decimal import Decimal
from fastapi import HTTPException
import models
import schemas
from config import settings
from audit import log_action
from exceptions import InsufficientFundsException
from models import AuditAction
from cache import cache_result, invalidate_cache
from typing import Optional
from datetime import datetime, timedelta
import pytz
import logging


# Import dual signing components
from dual_signing.dual_signing_service import DualSigningService
from dual_signing.nsdl_client import get_nsdl_client
from dual_signing.pdf_merger import PDFMerger
from document_generator import DocumentGenerator
from dual_signing_crud import get_dual_request, update_dual_request
from dual_signing.dual_signing_models import DualSigningStatus


IST = pytz.timezone("Asia/Kolkata")
logger = logging.getLogger(__name__)


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
    if not (0 <= loan.interest_rate <= 0.5):
        raise HTTPException(
            status_code=400,
            detail="Interest rate must be between 0% and 50%"
        )


def validate_users_exist(db: Session, lender_id: int, borrower_id: int):
    lender = db.query(models.User).filter(models.User.id == lender_id).first()
    borrower = db.query(models.User).filter(models.User.id == borrower_id).first()
    if not lender:
        raise HTTPException(status_code=404, detail="Lender not found")
    if not borrower:
        raise HTTPException(status_code=404, detail="Borrower not found")
    return lender, borrower


def get_wallet(db: Session, user_id: int):
    try:
        wallet = db.query(models.Wallet).filter(models.Wallet.user_id == user_id).first()
        if not wallet:
            wallet = models.Wallet(user_id=user_id, balance=Decimal("0.00"))
            db.add(wallet)
            db.commit()
            db.refresh(wallet)
        return wallet
    except Exception:
        db.rollback()
        raise



def create_loan(db: Session, loan: schemas.LoanCreate, callback_base_url: str = "http://localhost:8000"):
    """
    Create a loan without initiating dual signing. Signing happens after lender approval.
    """
    validate_loan_data(loan)
    lender, borrower = validate_users_exist(db, loan.lender_id, loan.borrower_id)

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

    start_date = datetime.now(IST)
    due_date = start_date + (freq_delta * loan.number_of_payments)

    try:
        db_loan = models.Loan(
            lender_id=loan.lender_id,
            borrower_id=loan.borrower_id,
            principal_amount=Decimal(str(loan.principal_amount)),
            interest_rate=Decimal(str(loan.interest_rate)),
            payment_frequency=loan.payment_frequency,
            number_of_payments=loan.number_of_payments,
            description=loan.description,
            start_date=start_date,
            due_date=due_date,
            status=models.LoanStatus.pending,
            sub_status=models.LoanSubStatus.none  # don't jump ahead to signing
        )
        db.add(db_loan)
        db.commit()
        db.refresh(db_loan)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create loan: {str(e)}")

    log_action(
        db=db,
        user_id=loan.borrower_id,
        action=AuditAction.LOAN_CREATED,
        description=f"Loan request #{db_loan.id} created by borrower",
        loan_id=db_loan.id
    )

    invalidate_cache(f"get_loans_by_user:{loan.lender_id}")
    invalidate_cache(f"get_loans_by_user:{loan.borrower_id}")

    return db_loan



def initiate_dual_signing_for_loan(db: Session, loan: models.Loan, callback_base_url: str = "http://localhost:8000"):
    """
    Initialize dual signing process for a loan
    """
    try:
        # 🔒 Check for existing dual signing request
        existing = get_dual_request(db, loan.id)
        if existing:
            if existing.status in [DualSigningStatus.FAILED, DualSigningStatus.CANCELLED]:
                update_dual_request(db, loan.id, {
                    "status": DualSigningStatus.PENDING_BORROWER,
                    "error_message": None,
                    "retry_count": 0
                })
                logger.info(f"[LOAN_ID:{loan.id}] Retrying dual signing")
            else:
                raise HTTPException(400, detail="Dual signing already in progress")

        # ✅ Now continue
        service = DualSigningService(
            nsdl_client=get_nsdl_client(),
            db=db,
            pdf_merger=PDFMerger(),
            document_generator=DocumentGenerator()
        )

        loan_data = {
            "loan_id": str(loan.id),
            "borrower_name": loan.borrower.name,
            "borrower_email": loan.borrower.email,
            "borrower_phone": loan.borrower.phone,
            "lender_name": loan.lender.name,
            "lender_email": loan.lender.email,
            "lender_phone": loan.lender.phone,
            "description": loan.description,
            "principal_amount": str(loan.principal_amount),
            "interest_rate": str(loan.interest_rate),
            "payment_frequency": loan.payment_frequency,
            "number_of_payments": loan.number_of_payments,
            "start_date": loan.start_date.isoformat() if loan.start_date else None,
            "due_date": loan.due_date.isoformat() if loan.due_date else None,
        }

        success, message, borrower_signing_url = service.create_and_initiate_dual_signing(
            loan_data=loan_data,
            callback_base_url=callback_base_url
        )

        return success, message, borrower_signing_url

    except Exception as e:
        logger.error(f"[LOAN_ID:{loan.id}] Error initiating dual signing: {str(e)}")
        return False, f"Failed to initiate dual signing: {str(e)}", None




def handle_dual_signing_completion(db: Session, loan_id: str):
    """
    Handle completion of dual signing process - called from dual signing callbacks
    """
    try:
        loan = db.query(models.Loan).filter(models.Loan.id == int(loan_id)).first()
        if not loan:
            logger.error(f"Loan {loan_id} not found for dual signing completion")
            return False

        loan.status = models.LoanStatus.active
        loan.sub_status = models.LoanSubStatus.fully_signed

        db.commit()
        db.refresh(loan)

        log_action(
            db=db,
            user_id=loan.borrower_id,
            action=AuditAction.LOAN_UPDATED,
            description=f"Loan #{loan.id} fully signed and activated",
            loan_id=loan.id
        )

        invalidate_cache(f"get_loans_by_user:{loan.lender_id}")
        invalidate_cache(f"get_loans_by_user:{loan.borrower_id}")

        logger.info(f"Loan {loan_id} successfully activated after dual signing completion")
        return True

    except Exception as e:
        db.rollback()
        logger.error(f"Error handling dual signing completion for loan {loan_id}: {str(e)}")
        return False



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
    loans = db.query(models.Loan)\
        .options(joinedload(models.Loan.payments))\
        .filter(
            (models.Loan.lender_id == user_id) |
            (models.Loan.borrower_id == user_id)
        ).all()

    return [
        schemas.LoanResponse.model_validate(loan, from_attributes=True)
        for loan in loans
    ]


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

    try:
        loan.status = new_status
        loan.sub_status = new_sub_status
        db.commit()
        db.refresh(loan)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update loan status: {str(e)}")

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
        try:
            db.delete(loan)
            db.commit()
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to delete loan: {str(e)}")
    return loan



def update_loan_sub_status(db: Session, loan_id: int, sub_status: schemas.LoanSubStatus):
    loan = db.query(models.Loan).filter(models.Loan.id == loan_id).first()
    if not loan:
        return None
    try:
        loan.sub_status = sub_status
        db.commit()
        db.refresh(loan)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update sub-status: {str(e)}")
    return loan
