from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional
from esign_service import NSDLESignService, NSDL_CONFIG
from agreement_generator import generate_loan_agreement_pdf
import os

router = APIRouter(prefix="/borrower", tags=["eSign"])

esign_service = NSDLESignService(NSDL_CONFIG)

class LoanSignRequest(BaseModel):
    loan_id: str
    borrower_name: str
    borrower_email: str
    borrower_phone: str
    aadhaar_last_4: str

class CallbackData(BaseModel):
    transactionId: str
    status: str
    signedDocUrl: Optional[str] = None
    errorMessage: Optional[str] = None
    timestamp: Optional[str] = None

@router.post("/request-signing")
def request_signing(data: LoanSignRequest) -> Dict:
    filename = f"loan_agreement_{data.loan_id}.pdf"
    pdf_path = generate_loan_agreement_pdf(
        loan_data=data.dict(),
        output_filename=filename
    )

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=500, detail="Failed to generate PDF")

    signing_request = esign_service.create_signing_request(data.dict(), pdf_path)
    result = esign_service.send_for_signing(signing_request, data.aadhaar_last_4)

    return result

@router.post("/esign/callback")
def handle_esign_callback(callback_data: CallbackData):
    result = esign_service.handle_callback(callback_data.dict())
    return result

@router.get("/esign/status/{transaction_id}")
def check_signing_status(transaction_id: str):
    signing_request = esign_service.get_signing_status(transaction_id)
    if not signing_request:
        raise HTTPException(status_code=404, detail="Signing request not found")
    return {
        "transaction_id": signing_request.transaction_id,
        "status": signing_request.status.value,
        "signed_at": signing_request.signed_at.isoformat() if signing_request.signed_at else None,
        "signing_url": signing_request.signing_url,
    }
