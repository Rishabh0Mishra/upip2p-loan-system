from sqlalchemy import Column, String, Enum, DateTime, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timedelta
from enum import Enum as PyEnum
from dataclasses import dataclass
from typing import Optional, Dict, Any

Base = declarative_base()

class SignerRole(PyEnum):
    BORROWER = "borrower"
    LENDER = "lender"

class DualSigningStatus(PyEnum):
    PENDING_BORROWER = "pending_borrower"
    BORROWER_SIGNED = "borrower_signed"
    PENDING_LENDER = "pending_lender"
    FULLY_SIGNED = "fully_signed"
    FAILED = "failed"
    EXPIRED = "expired"

class SigningRequestStatus(PyEnum):
    PENDING = "pending"
    NSDL_INITIATED = "nsdl_initiated"
    SIGNED = "signed"
    FAILED = "failed"
    EXPIRED = "expired"

class DualSigningRequest(Base):
    __tablename__ = "dual_signing_requests"

    loan_id = Column(String, primary_key=True)
    borrower_name = Column(String, nullable=False)
    borrower_email = Column(String, nullable=False)
    borrower_phone = Column(String, nullable=False)
    lender_name = Column(String, nullable=False)
    lender_email = Column(String, nullable=False)
    lender_phone = Column(String, nullable=False)
    document_url = Column(Text, nullable=False)
    document_hash = Column(String, nullable=True)

    status = Column(Enum(DualSigningStatus), default=DualSigningStatus.PENDING_BORROWER)
    borrower_signing_request_id = Column(String, nullable=True)
    lender_signing_request_id = Column(String, nullable=True)
    borrower_signed_doc_url = Column(Text, nullable=True)
    lender_signed_doc_url = Column(Text, nullable=True)
    fully_signed_doc_url = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    borrower_signed_at = Column(DateTime, nullable=True)
    lender_signed_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))

    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

class SigningRequest(Base):
    __tablename__ = "signing_requests"

    request_id = Column(String, primary_key=True)
    signer_name = Column(String, nullable=False)
    signer_email = Column(String, nullable=False)
    signer_phone = Column(String, nullable=False)
    document_url = Column(Text, nullable=False)
    callback_url = Column(Text, nullable=False)
    signer_role = Column(Enum(SignerRole), nullable=False)
    loan_id = Column(String, nullable=False)

    status = Column(Enum(SigningRequestStatus), default=SigningRequestStatus.PENDING)
    nsdl_request_id = Column(String, nullable=True)
    signed_document_url = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, default=lambda: datetime.utcnow() + timedelta(hours=24))
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)

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