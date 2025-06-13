from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from typing import Optional, List
from datetime import datetime

import models
import schemas
from audit import log_action


class LoanSearchService:
    def __init__(self, db: Session):
        self.db = db

    def search_loans(
        self,
        filters: schemas.LoanSearchFilters,
        user: models.User,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> schemas.LoanSearchResponse:
        """
        Advanced loan search with filtering, pagination, and sorting
        """
        log_action(
            self.db,
            user_id=user.id,
            action=models.AuditAction.LOAN_SEARCHED,
            description=f"Searched loans with filters: {filters.dict(exclude_none=True)}"
        )

        query = self.db.query(models.Loan)

        # Role-based access control
        if user.role == "borrower":
            query = query.filter(models.Loan.borrower_id == user.id)
        elif user.role == "lender":
            query = query.filter(models.Loan.lender_id == user.id)
        # Admin sees everything

        # Filters
        if filters.status:
            query = query.filter(models.Loan.status.in_(filters.status))
        if filters.min_amount:
            query = query.filter(models.Loan.principal_amount >= filters.min_amount)
        if filters.max_amount:
            query = query.filter(models.Loan.principal_amount <= filters.max_amount)
        if filters.lender_id:
            query = query.filter(models.Loan.lender_id == filters.lender_id)
        if filters.borrower_id:
            query = query.filter(models.Loan.borrower_id == filters.borrower_id)
        if filters.interest_rate_min:
            query = query.filter(models.Loan.interest_rate >= filters.interest_rate_min)
        if filters.interest_rate_max:
            query = query.filter(models.Loan.interest_rate <= filters.interest_rate_max)
        if filters.created_after:
            query = query.filter(models.Loan.created_at >= filters.created_after)
        if filters.created_before:
            query = query.filter(models.Loan.created_at <= filters.created_before)
        if filters.payment_frequency:
            query = query.filter(models.Loan.payment_frequency == filters.payment_frequency)
        if filters.start_date:
            query = query.filter(models.Loan.start_date >= filters.start_date)
        if filters.end_date:
            query = query.filter(models.Loan.due_date <= filters.end_date)

        # Sorting
        sort_column = getattr(models.Loan, sort_by, models.Loan.created_at)
        sort_column = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        query = query.order_by(sort_column)

        # Pagination
        total = query.count()
        loans = query.offset((page - 1) * page_size).limit(page_size).all()
        total_pages = (total + page_size - 1) // page_size

        # Prepare loan summaries
        loan_summaries = []
        for loan in loans:
            amount_paid = sum(p.amount for p in loan.payments if p.status == "completed")
            amount_remaining = float(loan.total_amount or 0) - amount_paid
            next_payment_date = next(
                (p.due_date for p in sorted(loan.payments, key=lambda x: x.due_date)
                if p.status == "pending"), None
            )

            summary = schemas.LoanSummary(
                id=loan.id,
                lender_id=loan.lender_id,
                borrower_id=loan.borrower_id,
                principal_amount=float(loan.principal_amount),
                interest_rate=float(loan.interest_rate),
                total_amount=float(loan.total_amount),
                payment_frequency=loan.payment_frequency.value,
                number_of_payments=loan.number_of_payments,
                payment_amount=float(loan.payment_amount),
                start_date=loan.start_date,
                due_date=loan.due_date,
                next_payment_date=next_payment_date,
                status=loan.status,
                sub_status=loan.sub_status,
                amount_paid=amount_paid,
                amount_remaining=amount_remaining,
                description=loan.description,
                created_at=loan.created_at,
                updated_at=loan.updated_at
            )
            loan_summaries.append(summary)

        return schemas.LoanSearchResponse(
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            results=loan_summaries
        )
