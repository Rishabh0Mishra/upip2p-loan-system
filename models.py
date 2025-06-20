from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, DateTime,
    Numeric, Text, Float, Date, func
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.types import Enum as SqlEnum
from datetime import datetime
import pytz
import enum
from database import Base

IST = pytz.timezone("Asia/Kolkata")

# Enums as Python classes
class PaymentStatus(str, enum.Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

class TransactionType(str, enum.Enum):
    credit = "credit"
    debit = "debit"

class TransactionStatus(str, enum.Enum):
    success = "success"
    failed = "failed"

# PostgreSQL-native ENUM types
payment_status_enum = PG_ENUM(
    PaymentStatus,
    name="paymentstatus",
    create_type=True,
    metadata=Base.metadata
)

transaction_type_enum = PG_ENUM(
    TransactionType,
    name="transaction_type",
    create_type=True,
    metadata=Base.metadata
)

transaction_status_enum = PG_ENUM(
    TransactionStatus,
    name="transaction_status",
    create_type=True,
    metadata=Base.metadata
)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    upi_id = Column(String, nullable=True)
    role = Column(String, default="borrower")
    phone = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    email_verification = relationship("EmailVerificationToken", back_populates="user", uselist=False, cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    wallet = relationship("Wallet", back_populates="user", uselist=False)

class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False)
    user = relationship("User", back_populates="tokens")

class EmailVerificationToken(Base):
    __tablename__ = "email_verification_tokens"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    token = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(IST))
    is_verified = Column(Boolean, default=False)
    user = relationship("User", back_populates="email_verification")

class LoanStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    defaulted = "defaulted"

class LoanSubStatus(str, enum.Enum):
    none = "none"
    waiting_reinitiation = "waiting_reinitiation"
    overdue = "overdue"
    partially_paid = "partially_paid"

class PaymentFrequency(str, enum.Enum):
    every_10_seconds = "every_10_seconds"
    every_30_seconds = "every_30_seconds"
    minutely = "minutely"
    every_5_minutes = "every_5_minutes"
    hourly = "hourly"
    daily = "daily"
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    one_time = "one_time"

class Loan(Base):
    __tablename__ = "loans"
    id = Column(Integer, primary_key=True, index=True)
    lender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    borrower_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    principal_amount = Column(Numeric(12, 2), nullable=False)
    interest_rate = Column(Numeric(5, 2), nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0)

    payment_frequency = Column(SqlEnum(PaymentFrequency, name="payment_frequency_enum", native_enum=False), default=PaymentFrequency.monthly)
    number_of_payments = Column(Integer, nullable=False, default=1)
    payment_amount = Column(Numeric(10, 2), nullable=False, default=0)

    start_date = Column(DateTime, nullable=True)
    due_date = Column(DateTime, nullable=True)
    next_payment_date = Column(DateTime, nullable=True)

    status = Column(SqlEnum(LoanStatus, name="loan_status_enum", native_enum=False), default=LoanStatus.pending, nullable=False)
    sub_status = Column(SqlEnum(LoanSubStatus, name="loan_substatus_enum", native_enum=False), default=LoanSubStatus.none, nullable=False)

    amount_paid = Column(Numeric(12, 2), default=0)
    amount_remaining = Column(Numeric(12, 2), nullable=False, default=0)

    description = Column(Text, nullable=True)

    # ✅ Add this field to store final signed agreement
    signed_agreement_url = Column(String, nullable=True)

    created_at = Column(DateTime, default=lambda: datetime.now(IST))
    updated_at = Column(DateTime, default=lambda: datetime.now(IST), onupdate=lambda: datetime.now(IST))

    lender = relationship("User", foreign_keys=[lender_id])
    borrower = relationship("User", foreign_keys=[borrower_id])
    payments = relationship("Payment", back_populates="loan", cascade="all, delete-orphan")
    documents = relationship("LoanDocument", back_populates="loan")


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"))
    amount = Column(Float, nullable=False)
    status = Column(payment_status_enum, nullable=False, default="pending")

    due_date = Column(DateTime(timezone=True), nullable=False)   # <- datetime!
    paid_date = Column(DateTime(timezone=True), nullable=True)   # <- datetime!

    txn_reference = Column(String, nullable=True)
    principal_portion = Column(Float, nullable=False, default=0)
    interest_portion = Column(Float, nullable=False, default=0)
    late_fee = Column(Float, nullable=False, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(IST))

    loan = relationship("Loan", back_populates="payments")
    
class NotificationType(str, enum.Enum):
    LOAN_REQUEST = "loan_request"
    LOAN_APPROVED = "loan_approved"
    LOAN_REJECTED = "loan_rejected"
    PAYMENT_DUE = "payment_due"
    PAYMENT_OVERDUE = "payment_overdue"
    PAYMENT_RECEIVED = "payment_received"
    LOAN_COMPLETED = "loan_completed"
    SYSTEM_ALERT = "system_alert"

class NotificationChannel(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    type = Column(SqlEnum(NotificationType, name="notification_type_enum", native_enum=False), nullable=False)
    channel = Column(SqlEnum(NotificationChannel, name="notification_channel_enum", native_enum=False), nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    is_read = Column(Boolean, default=False)
    is_sent = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    scheduled_for = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(IST))
    user = relationship("User", back_populates="notifications")
    loan = relationship("Loan")
    payment = relationship("Payment")

class AuditAction(str, enum.Enum):
    ROLE_CHANGE = "role_change"
    LOAN_CREATED = "loan_created"
    LOAN_UPDATED = "loan_updated"
    LOAN_STATUS_UPDATED = "loan_status_updated"
    PAYMENT_MADE = "payment_made"
    PAYMENT_FAILED = "payment_failed"
    NOTIFICATION_SENT = "notification_sent"
    PASSWORD_CHANGED = "password_changed"
    PROFILE_UPDATED = "profile_updated"
    LOGIN = "login"
    LOAN_SEARCHED = "loan_searched"
    EMAIL_VERIFIED = "email_verified"
    MANDATE_FAILED = "mandate_failed"
    WALLET_TOPUP = "wallet_topup"
    loan_approved = "loan_approved"

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action = Column(SqlEnum(AuditAction, name="audit_action_enum", native_enum=False), nullable=False)
    description = Column(String, nullable=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=True)
    payment_id = Column(Integer, ForeignKey("payments.id"), nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(IST))
    user = relationship("User")
    loan = relationship("Loan")
    payment = relationship("Payment")

class LoanDocument(Base):
    __tablename__ = "loan_documents"
    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id"), nullable=False)
    document_type = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(IST))
    loan = relationship("Loan", back_populates="documents")
    uploader = relationship("User")

class PaymentRetryStatus(str, enum.Enum):
    success = "success"
    failed = "failed"

class PaymentRetryLog(Base):
    __tablename__ = "payment_retry_logs"
    id = Column(Integer, primary_key=True, index=True)
    payment_id = Column(Integer, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False)
    attempted_at = Column(DateTime, default=lambda: datetime.now(IST))
    status = Column(SqlEnum(PaymentRetryStatus, name="retry_status_enum", native_enum=False), nullable=False)
    notes = Column(Text, nullable=True)
    payment = relationship("Payment")

class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id = Column(Integer, primary_key=True, index=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"))
    amount = Column(Numeric(precision=12, scale=2))
    type = Column(transaction_type_enum, nullable=False)
    reason = Column(String(255))
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(transaction_status_enum, nullable=False)
    wallet = relationship("Wallet", back_populates="transactions")


class Wallet(Base):
    __tablename__ = "wallets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True)
    balance = Column(Numeric(precision=12, scale=2), default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="wallet")
    transactions = relationship("WalletTransaction", back_populates="wallet", cascade="all, delete-orphan")
