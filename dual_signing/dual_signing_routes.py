from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Dict, Any
import logging
import os

from .dual_signing_service import DualSigningService
from .nsdl_client import NSDLClient, MockNSDLClient
from .dual_signing_models import DualSigningStatus
from dependencies import require_roles, get_db, get_current_user

from models import SigningRequest, SignerRole, Loan
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dual-signing", tags=["Dual Signing"])
require_admin = require_roles(["admin"])

# Use mock NSDL client in development
use_mock = os.getenv("USE_MOCK_NSDL", "true").lower() == "true"

def get_dual_signing_service(db: Session = Depends(get_db)) -> DualSigningService:
    client = MockNSDLClient() if use_mock else NSDLClient()
    return DualSigningService(nsdl_client=client, db=db)


@router.post("/initiate", dependencies=[Depends(require_admin)])
async def initiate_dual_signing(
    request: Request,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        data = await request.json()
        required_fields = [
            'loan_id', 'borrower_name', 'borrower_email', 'borrower_phone',
            'lender_name', 'lender_email', 'lender_phone', 'document_url'
        ]
        missing = [f for f in required_fields if not data.get(f)]
        if missing:
            raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

        for email in [data['borrower_email'], data['lender_email']]:
            if '@' not in email:
                raise HTTPException(status_code=400, detail=f"Invalid email: {email}")

        for phone in [data['borrower_phone'], data['lender_phone']]:
            digits = phone.replace("+", "").replace("-", "").replace(" ", "")
            if len(digits) < 10:
                raise HTTPException(status_code=400, detail=f"Invalid phone: {phone}")

        callback_base_url = data.get("callback_base_url", "http://localhost:8000")
        success, message, signing_url = service.initiate_dual_signing(
            loan_id=data['loan_id'],
            borrower_name=data['borrower_name'],
            borrower_email=data['borrower_email'],
            borrower_phone=data['borrower_phone'],
            lender_name=data['lender_name'],
            lender_email=data['lender_email'],
            lender_phone=data['lender_phone'],
            document_url=data['document_url'],
            callback_base_url=callback_base_url
        )
        return JSONResponse(
            status_code=200 if success else 400,
            content={
                "success": success,
                "message": message,
                "borrower_signing_url": signing_url if success else None,
                "loan_id": data['loan_id']
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"initiate_dual_signing error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.post("/callback/borrower")
async def borrower_signing_callback(
    request: Request,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        data = await request.json()
        logger.info(f"Borrower callback: {data}")
        success, message = service.handle_borrower_signing_callback(data)
        return JSONResponse(
            status_code=200 if success else 400,
            content={"success": success, "message": message}
        )
    except Exception as e:
        logger.error(f"Borrower callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.post("/callback/lender")
async def lender_signing_callback(
    request: Request,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        data = await request.json()
        logger.info(f"Lender callback: {data}")
        success, message = service.handle_lender_signing_callback(data)
        return JSONResponse(
            status_code=200 if success else 400,
            content={"success": success, "message": message}
        )
    except Exception as e:
        logger.error(f"Lender callback error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.get("/status/{loan_id}")
def get_signing_status(
    loan_id: str,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        status_data = service.get_dual_signing_status(loan_id)
        if not status_data:
            raise HTTPException(status_code=404, detail="Signing request not found")
        return JSONResponse(
            status_code=200,
            content={"success": True, "data": status_data}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Status check error for loan {loan_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.get("/loans", dependencies=[Depends(require_admin)])
def get_all_loan_signings(
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        all_data = service.get_all_dual_signing_requests()
        return JSONResponse(
            status_code=200,
            content={"success": True, "data": all_data, "count": len(all_data)}
        )
    except Exception as e:
        logger.error(f"Get all loan signings error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.post("/retry/{loan_id}", dependencies=[Depends(require_admin)])
async def retry_failed_signing(
    loan_id: str,
    request: Request,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        data = await request.json()
        callback_base_url = data.get("callback_base_url", "http://localhost:8000")
        success, message = service.retry_failed_signing(loan_id, callback_base_url)
        return JSONResponse(
            status_code=200 if success else 400,
            content={"success": success, "message": message, "loan_id": loan_id}
        )
    except Exception as e:
        logger.error(f"Retry error for loan {loan_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.post("/cancel/{loan_id}", dependencies=[Depends(require_admin)])
async def cancel_dual_signing(
    loan_id: str,
    request: Request,
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        data = await request.json()
        reason = data.get("reason", "Cancelled by user")
        success, message = service.cancel_dual_signing(loan_id, reason)
        return JSONResponse(
            status_code=200 if success else 400,
            content={"success": success, "message": message, "loan_id": loan_id}
        )
    except Exception as e:
        logger.error(f"Cancel signing error for loan {loan_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.get("/statistics", dependencies=[Depends(require_admin)])
def get_signing_statistics(
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        stats = service.get_signing_statistics()
        return JSONResponse(
            status_code=200,
            content={"success": True, "data": stats}
        )
    except Exception as e:
        logger.error(f"Statistics error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


@router.post("/cleanup-expired", dependencies=[Depends(require_admin)])
async def cleanup_expired_requests(
    service: DualSigningService = Depends(get_dual_signing_service)
):
    try:
        count = service.cleanup_expired_requests()
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": f"Marked {count} expired requests",
                "expired_count": count
            }
        )
    except Exception as e:
        logger.error(f"Cleanup expired requests error: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {e}")


# ✅ NEW endpoint to get signing request ID
class GetSigningRequestIdInput(BaseModel):
    loan_id: int

@router.post("/get-request-id", tags=["Dual Signing"])
def get_own_signing_request_id(
    payload: GetSigningRequestIdInput,
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    loan = db.query(Loan).filter(Loan.id == payload.loan_id).first()
    if not loan:
        raise HTTPException(status_code=404, detail="Loan not found.")

    if loan.borrower_id == current_user.id:
        role = SignerRole.BORROWER
    elif loan.lender_id == current_user.id:
        role = SignerRole.LENDER
    else:
        raise HTTPException(status_code=403, detail="You are not part of this loan.")

    signing_request = db.query(SigningRequest).filter(
        SigningRequest.loan_id == loan.id,
        SigningRequest.signer_role == role
    ).first()

    if not signing_request:
        raise HTTPException(status_code=404, detail="Signing request not found.")

    return {
        "loan_id": loan.id,
        "signer_role": role.value,
        "signing_request_id": signing_request.request_id
    }
