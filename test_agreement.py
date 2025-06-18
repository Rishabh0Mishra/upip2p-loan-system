from agreement_generator import generate_loan_agreement_pdf
import uuid
from datetime import datetime, timedelta

# Calculate EMI and total amount (simple calculation)
principal = 5000
rate = 12.5 / 100 / 12  # Monthly interest rate
num_payments = 6
emi = principal * (rate * (1 + rate)**num_payments) / ((1 + rate)**num_payments - 1)
total_amount = emi * num_payments

loan_data = {
    "borrower_name": "Ravi Kumar",
    "borrower_email": "ravi.kumar@email.com",
    "borrower_phone": "+91 9876543210",
    "lender_name": "Ronny Dealer", 
    "lender_email": "ronny.dealer@email.com",
    "lender_phone": "+91 9123456789",
    "amount": 5000,
    "interest_rate": 12.5,
    "num_payments": 6,
    "start_date": "2025-06-18",
    "end_date": "2025-12-18",
    "emi_amount": f"{emi:.2f}",
    "total_amount": f"{total_amount:.2f}",
    "loan_id": f"LOAN-{str(uuid.uuid4())[:8].upper()}",
    "generated_date": datetime.now().strftime("%d/%m/%Y %I:%M %p")
}

try:
    output_file = generate_loan_agreement_pdf(loan_data, "test_agreement.pdf")
    print("Agreement saved to:", output_file)
    print("\nLoan Details:")
    print(f"Principal: ₹{loan_data['amount']}")
    print(f"EMI: ₹{loan_data['emi_amount']}")
    print(f"Total Repayment: ₹{loan_data['total_amount']}")
    print(f"Loan ID: {loan_data['loan_id']}")
except Exception as e:
    print(f"Error generating PDF: {e}")