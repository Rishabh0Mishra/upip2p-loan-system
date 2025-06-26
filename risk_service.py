from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_
from models import User, Payment, Loan, PaymentStatus
from datetime import timedelta, datetime
from typing import Dict, Optional
import logging

from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

# Configure grace period (as you suggested - constant 60 seconds)
GRACE_PERIOD = timedelta(seconds=60)

# Risk score weights for different factors
RISK_WEIGHTS = {
    'punctuality': 0.60,      # 60% - Most important
    'payment_history': 0.25,  # 25% - Overall payment behavior
    'recent_performance': 0.15 # 15% - Recent 30 days performance
}

def calculate_risk_score(db: Session, user_id: int) -> float:
    """
    Calculate comprehensive risk score for a user based on:
    1. Payment punctuality (60% weight)
    2. Overall payment history (25% weight) 
    3. Recent performance (15% weight)
    
    Score: 0-100 (100 = lowest risk, 0 = highest risk)
    """
    try:
        # Fetch user with error handling
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            logging.warning(f"User {user_id} not found for risk score calculation")
            return 0.0

        # Fetch all completed payments for this borrower with optimized query
        payments = (
            db.query(Payment)
            .join(Loan, Payment.loan_id == Loan.id)
            .filter(
                Loan.borrower_id == user_id,
                Payment.status == PaymentStatus.completed,
                Payment.paid_date.isnot(None),
                Payment.due_date.isnot(None)
            )
            .order_by(Payment.due_date.desc())
            .all()
        )

        # Handle edge cases
        if not payments:
            # New user with no payment history
            score = 75.0  # Neutral score for new users (instead of 100)
            user.risk_score = score
            db.commit()
            return score

        # Calculate different risk components
        punctuality_score = _calculate_punctuality_score(payments)
        payment_history_score = _calculate_payment_history_score(payments)
        recent_performance_score = _calculate_recent_performance_score(payments)

        # Weighted final score
        final_score = (
            punctuality_score * RISK_WEIGHTS['punctuality'] +
            payment_history_score * RISK_WEIGHTS['payment_history'] +
            recent_performance_score * RISK_WEIGHTS['recent_performance']
        )

        # Round and clamp between 0-100
        final_score = max(0.0, min(100.0, round(final_score, 2)))

        # Update user record
        user.risk_score = final_score
        user.risk_score_updated_at = datetime.now(IST)  # Track when it was last updated
        db.commit()

        logging.info(f"Risk score calculated for user {user_id}: {final_score}")
        return final_score

    except Exception as e:
        logging.error(f"Error calculating risk score for user {user_id}: {str(e)}")
        db.rollback()
        return 0.0  # Conservative score on error


def _calculate_punctuality_score(payments: list) -> float:
    """Calculate punctuality score based on on-time payments within grace period"""
    if not payments:
        return 75.0  # Neutral score
    
    on_time_count = 0
    total_count = len(payments)
    
    for payment in payments:
        grace_deadline = payment.due_date + GRACE_PERIOD
        if payment.paid_date <= grace_deadline:
            on_time_count += 1
    
    punctuality_ratio = on_time_count / total_count
    return punctuality_ratio * 100


def _calculate_payment_history_score(payments: list) -> float:
    """Calculate score based on overall payment consistency and patterns"""
    if not payments:
        return 75.0
    
    total_payments = len(payments)
    
    # Bonus for payment history length (more history = more reliable data)
    history_bonus = min(10, total_payments * 0.5)  # Max 10 points bonus
    
    # Penalty for any severely late payments (>7 days late)
    severely_late_count = 0
    for payment in payments:
        days_late = (payment.paid_date - payment.due_date).days
        if days_late > 7:
            severely_late_count += 1
    
    severe_late_penalty = (severely_late_count / total_payments) * 20  # Max 20 points penalty
    
    base_score = 80.0  # Base score for having payment history
    return max(0, base_score + history_bonus - severe_late_penalty)


def _calculate_recent_performance_score(payments: list) -> float:
    """Calculate score based on recent 30 days performance (higher weight on recent behavior)"""
    if not payments:
        return 75.0
    
    # Filter payments from last 30 days
    thirty_days_ago = datetime.now(IST) - timedelta(days=30)
    recent_payments = [p for p in payments if p.due_date >= thirty_days_ago]
    
    if not recent_payments:
        # No recent payments, use overall performance as proxy
        return _calculate_punctuality_score(payments[-5:])  # Last 5 payments
    
    # Recent punctuality is more critical
    recent_on_time = 0
    for payment in recent_payments:
        grace_deadline = payment.due_date + GRACE_PERIOD
        if payment.paid_date <= grace_deadline:
            recent_on_time += 1
    
    recent_ratio = recent_on_time / len(recent_payments)
    return recent_ratio * 100


def get_risk_category(risk_score: float) -> str:
    """Convert numerical risk score to category"""
    if risk_score >= 80:
        return "LOW_RISK"
    elif risk_score >= 60:
        return "MEDIUM_RISK"
    elif risk_score >= 40:
        return "HIGH_RISK"
    else:
        return "VERY_HIGH_RISK"


def get_risk_score_breakdown(db: Session, user_id: int) -> Dict:
    """Get detailed breakdown of risk score components for transparency"""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return {}
    
    payments = (
        db.query(Payment)
        .join(Loan, Payment.loan_id == Loan.id)
        .filter(
            Loan.borrower_id == user_id,
            Payment.status == PaymentStatus.completed,
            Payment.paid_date.isnot(None),
            Payment.due_date.isnot(None)
        )
        .order_by(Payment.due_date.desc())
        .all()
    )
    
    return {
        "user_id": user_id,
        "current_risk_score": user.risk_score,
        "risk_category": get_risk_category(user.risk_score or 0),
        "total_payments": len(payments),
        "punctuality_score": _calculate_punctuality_score(payments),
        "payment_history_score": _calculate_payment_history_score(payments),
        "recent_performance_score": _calculate_recent_performance_score(payments),
        "last_updated": user.risk_score_updated_at,
        "components": {
            "punctuality_weight": f"{RISK_WEIGHTS['punctuality']*100}%",
            "payment_history_weight": f"{RISK_WEIGHTS['payment_history']*100}%",
            "recent_performance_weight": f"{RISK_WEIGHTS['recent_performance']*100}%"
        }
    }


# Usage in your loan approval/interest rate logic:
def get_interest_rate_adjustment(risk_score: float) -> float:
    """Adjust interest rates based on risk score"""
    if risk_score >= 90:
        return -0.5  # 0.5% discount for excellent borrowers
    elif risk_score >= 80:
        return 0.0   # Standard rate
    elif risk_score >= 60:
        return 0.5   # 0.5% premium
    elif risk_score >= 40:
        return 1.0   # 1% premium
    else:
        return 2.0   # 2% premium for high-risk borrowers