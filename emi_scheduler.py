from decimal import Decimal
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import pytz

from models import Payment, Loan, PaymentStatus
from schemas import PaymentFrequency

IST = pytz.timezone("Asia/Kolkata")


def create_repayment_schedule(db: Session, loan: Loan):
    if loan.status != "active":
        raise ValueError("Repayment schedule can only be created for active loans")

    frequency = loan.payment_frequency.lower()
    num_payments = loan.number_of_payments
    principal = loan.principal_amount
    rate = loan.interest_rate or Decimal("0.0")

    if not frequency or not num_payments:
        raise ValueError("Loan must have payment_frequency and number_of_payments defined")

    # Total repayment = principal + interest
    total_amount = principal * (Decimal("1") + rate / Decimal("100"))
    emi_amount = (total_amount / num_payments).quantize(Decimal("0.01"))

    # Interval map with timedelta objects (TEST-FRIENDLY)
    freq_map = {
        "every_10_seconds": timedelta(seconds=10),
        "every_30_seconds": timedelta(seconds=30),
        "minutely": timedelta(minutes=1),
        "every_5_minutes": timedelta(minutes=5),
        "hourly": timedelta(hours=1),
        "daily": timedelta(days=1),
        "weekly": timedelta(weeks=1),
        "biweekly": timedelta(weeks=2),
        "monthly": timedelta(days=30),
        "quarterly": timedelta(days=90),
        "one_time": timedelta(days=0),
    }

    delta = freq_map.get(frequency)
    if not delta:
        raise ValueError(f"Unsupported payment frequency: {frequency}")

    # FIXED: Proper spacing - first EMI starts after one full interval
    # This gives borrower time before first payment is due
    start_time = datetime.now(IST)
    
    for i in range(num_payments):
        # Each EMI is spaced by exactly one interval from the start
        # EMI 1: start + 1*delta, EMI 2: start + 2*delta, etc.
        due_date = start_time + (delta * (i + 1))
        
        payment = Payment(
            loan_id=loan.id,
            amount=emi_amount,
            due_date=due_date,
            status=PaymentStatus.pending,
            emi_number=i + 1 
        )
        db.add(payment)

    db.commit()
    print(f"📅 Created EMI schedule for Loan #{loan.id}: ₹{emi_amount} x {num_payments} @ {frequency}")
    
    # Debug: Print all due dates for verification
    payments = db.query(Payment).filter(Payment.loan_id == loan.id).order_by(Payment.due_date).all()
    for payment in payments:
        print(f"   EMI #{payment.emi_number}: Due at {payment.due_date.strftime('%H:%M:%S')}")
