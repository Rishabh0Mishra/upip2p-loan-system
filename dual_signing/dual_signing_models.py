from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

class SignerRole(Enum):
    BORROWER = "borrower"
    LENDER = "lender"

class DualSigningStatus(Enum):
    PENDING_BORROWER = "pending_borrower"
    BORROWER_SIGNED = "borrower_signed"
    PENDING_LENDER = "pending_lender"
    FULLY_SIGNED = "fully_signed"
    FAILED = "failed"
    EXPIRED = "expired"

class SigningRequestStatus(Enum):
    PENDING = "pending"
    NSDL_INITIATED = "nsdl_initiated"
    SIGNED = "signed"
    FAILED = "failed"
    EXPIRED = "expired"

@dataclass
class DualSigningRequest:
    loan_id: str
    borrower_name: str
    borrower_email: str
    borrower_phone: str
    lender_name: str
    lender_email: str
    lender_phone: str
    document_url: str
    document_hash: Optional[str] = None
    status: DualSigningStatus = DualSigningStatus.PENDING_BORROWER
    borrower_signing_request_id: Optional[str] = None
    lender_signing_request_id: Optional[str] = None
    borrower_signed_doc_url: Optional[str] = None
    lender_signed_doc_url: Optional[str] = None
    fully_signed_doc_url: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    borrower_signed_at: Optional[datetime] = None
    lender_signed_at: Optional[datetime] = None
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))
    error_message: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at
    
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "loan_id": self.loan_id,
            "borrower_name": self.borrower_name,
            "lender_name": self.lender_name,
            "status": self.status.value,
            "borrower_signed_doc_url": self.borrower_signed_doc_url,
            "lender_signed_doc_url": self.lender_signed_doc_url,
            "fully_signed_doc_url": self.fully_signed_doc_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "borrower_signed_at": self.borrower_signed_at.isoformat() if self.borrower_signed_at else None,
            "lender_signed_at": self.lender_signed_at.isoformat() if self.lender_signed_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "error_message": self.error_message,
            "retry_count": self.retry_count
        }

@dataclass
class SigningRequest:
    request_id: str
    signer_name: str
    signer_email: str
    signer_phone: str
    document_url: str
    callback_url: str
    signer_role: SignerRole
    loan_id: str
    status: SigningRequestStatus = SigningRequestStatus.PENDING
    nsdl_request_id: Optional[str] = None
    signed_document_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))
    retry_count: int = 0
    max_retries: int = 3
    
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at
    
    def can_retry(self) -> bool:
        return self.retry_count < self.max_retries
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "signer_name": self.signer_name,
            "signer_email": self.signer_email,
            "signer_role": self.signer_role.value,
            "loan_id": self.loan_id,
            "status": self.status.value,
            "nsdl_request_id": self.nsdl_request_id,
            "signed_document_url": self.signed_document_url,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "retry_count": self.retry_count
        }

@dataclass
class NSDLResponse:
    status: str
    request_id: Optional[str] = None
    signing_url: Optional[str] = None
    signed_document_url: Optional[str] = None
    error_message: Optional[str] = None
    
    @classmethod
    def success(cls, request_id: str, signing_url: str) -> 'NSDLResponse':
        return cls(status="SUCCESS", request_id=request_id, signing_url=signing_url)
    
    @classmethod
    def error(cls, error_message: str) -> 'NSDLResponse':
        return cls(status="ERROR", error_message=error_message)

@dataclass
class SigningCallbackData:
    request_id: str
    status: str
    signed_document_url: Optional[str] = None
    error_message: Optional[str] = None
    signature_details: Optional[Dict[str, Any]] = None
    
    def is_successful(self) -> bool:
        return self.status.upper() == "SIGNED"