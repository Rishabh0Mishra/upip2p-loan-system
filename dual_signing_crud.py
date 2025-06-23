from typing import List, Dict, Any
from sqlalchemy.orm import Session
from dual_signing.dual_signing_models import DualSigningRequest, SigningRequest, DualSigningStatus
from datetime import datetime, timedelta
from sqlalchemy import func
from fastapi import HTTPException

def get_all_dual_requests(db: Session) -> List[DualSigningRequest]:
    """Get all dual signing requests"""
    return db.query(DualSigningRequest).all()


def create_dual_request(db: Session, request: DualSigningRequest) -> DualSigningRequest:
    """Create a dual signing request"""
    try:
        db.add(request)
        db.commit()
        db.refresh(request)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create dual request: {str(e)}")
    return request



def get_dual_request(db: Session, loan_id: int) -> DualSigningRequest:
    """Fetch a dual signing request by loan ID"""
    return db.query(DualSigningRequest).filter(DualSigningRequest.loan_id == loan_id).first()


def update_dual_request_status(
    db: Session, loan_id: int,
    status: DualSigningStatus,
    error_message: str = None
) -> DualSigningRequest:
    """Update the status (and optionally error message) of a dual signing request"""
    try:
        dual_request = db.query(DualSigningRequest).filter(DualSigningRequest.loan_id == loan_id).first()
        if dual_request:
            dual_request.status = status
            if error_message:
                dual_request.error_message = error_message
            db.commit()
            db.refresh(dual_request)
        return dual_request
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to update dual request status: {str(e)}")


def save_signed_document(db: Session, loan_id: int, merged_document_url: str) -> DualSigningRequest:
    """Save the final signed document URL after merging both signatures"""
    try:
        dual_request = db.query(DualSigningRequest).filter(DualSigningRequest.loan_id == loan_id).first()
        if dual_request:
            dual_request.final_document_url = merged_document_url
            db.commit()
            db.refresh(dual_request)
        return dual_request
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save final signed document: {str(e)}")


def create_signing_request(db: Session, signing_request: SigningRequest) -> SigningRequest:
    """Create a new signing request"""
    try:
        db.add(signing_request)
        db.commit()
        db.refresh(signing_request)
        return signing_request
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to create signing request: {str(e)}")

def get_signing_request(db: Session, request_id: str) -> SigningRequest:
    """Get signing request by request_id"""
    return db.query(SigningRequest).filter(SigningRequest.request_id == request_id).first()


def update_dual_request(
    db: Session,
    loan_id: int,
    updates: Dict[str, Any]
) -> DualSigningRequest:
    """Update dual signing request with given updates"""
    dual_request = db.query(DualSigningRequest).filter(DualSigningRequest.loan_id == loan_id).first()
    if dual_request:
        try:
            for key, value in updates.items():
                setattr(dual_request, key, value)
            db.commit()
            db.refresh(dual_request)
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to update dual signing request: {str(e)}")
    return dual_request

def mark_expired_requests(db: Session) -> int:
    """Mark requests older than 7 days as expired"""
    expiry_date = datetime.utcnow() - timedelta(days=7)

    try:
        expired_count = db.query(DualSigningRequest).filter(
            DualSigningRequest.created_at < expiry_date,
            DualSigningRequest.status.in_([
                DualSigningStatus.PENDING_BORROWER,
                DualSigningStatus.BORROWER_SIGNED,
                DualSigningStatus.PENDING_LENDER
            ])
        ).update({
            "status": DualSigningStatus.FAILED,
            "error_message": "Request expired after 7 days"
        }, synchronize_session=False)

        db.commit()
        return expired_count

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to mark expired requests: {str(e)}")



def get_statistics(db: Session) -> Dict[str, Any]:
    """Get signing statistics"""
    stats = db.query(
        DualSigningRequest.status,
        func.count(DualSigningRequest.id).label('count')
    ).group_by(DualSigningRequest.status).all()

    total_requests = db.query(func.count(DualSigningRequest.id)).scalar()

    successful = db.query(func.count(DualSigningRequest.id)).filter(
        DualSigningRequest.status == DualSigningStatus.FULLY_SIGNED
    ).scalar()

    return {
        "total_requests": total_requests,
        "status_breakdown": {
            status.value if hasattr(status, "value") else str(status): count
            for status, count in stats
        },
        "success_rate": round((successful / total_requests * 100), 2) if total_requests else 0
    }
def update_signing_request(
    db: Session,
    request_id: str,
    updates: Dict[str, Any]
) -> SigningRequest:
    """Update fields in a signing request"""
    signing_request = db.query(SigningRequest).filter(SigningRequest.request_id == request_id).first()
    if signing_request:
        try:
            for key, value in updates.items():
                setattr(signing_request, key, value)
            db.commit()
            db.refresh(signing_request)
        except Exception as e:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Failed to update signing request: {str(e)}")
    return signing_request
