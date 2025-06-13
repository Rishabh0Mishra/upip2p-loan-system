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

    # Schedule starts from now + delta
    start_date = datetime.now(IST) + delta

    for i in range(num_payments):
        due_date = start_date + (delta * i)
        payment = Payment(
            loan_id=loan.id,
            amount=emi_amount,
            due_date=due_date,
            status=PaymentStatus.pending,
        )
        db.add(payment)

    db.commit()
    print(f"📅 Created EMI schedule for Loan #{loan.id}: ₹{emi_amount} x {num_payments} @ {frequency}")
