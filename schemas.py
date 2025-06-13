from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
import re

# ==== ENUMS ====

class RoleType(str, Enum):
    admin = "admin"
    lender = "lender"
    borrower = "borrower"

class LoanStatus(str, Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"
    defaulted = "defaulted"

class LoanSubStatus(str, Enum):
    none = "none"
    waiting_reinitiation = "waiting_reinitiation"
    overdue = "overdue"
    partially_paid = "partially_paid"

class PaymentFrequency(str, Enum):
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

class PaymentStatus(str, Enum):
    pending = "pending"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    
# ==== ENUMS ====

class PaymentRetryStatus(str, Enum):
    success = "success"
    failed = "failed"
    

class NotificationType(str, Enum):
    LOAN_REQUEST = "loan_request"
    LOAN_APPROVED = "loan_approved"
    LOAN_REJECTED = "loan_rejected"
    PAYMENT_DUE = "payment_due"
    PAYMENT_OVERDUE = "payment_overdue"
    PAYMENT_RECEIVED = "payment_received"
    LOAN_COMPLETED = "loan_completed"
    SYSTEM_ALERT = "system_alert"

class NotificationChannel(str, Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"
    IN_APP = "in_app"

# ==== VALIDATORS ====

UPI_REGEX = r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{3,}$'

def validate_upi_id(upi_id: Optional[str]) -> Optional[str]:
    if upi_id and not re.match(UPI_REGEX, upi_id):
        raise ValueError("Invalid UPI ID format")
    return upi_id

def validate_password_strength(password: str) -> str:
    if len(password) < 8:
        raise ValueError('Password must be at least 8 characters long')
    if not re.search(r'[A-Z]', password):
        raise ValueError('Password must contain at least one uppercase letter')
    if not re.search(r'[a-z]', password):
        raise ValueError('Password must contain at least one lowercase letter')
    if not re.search(r'\d', password):
        raise ValueError('Password must contain at least one digit')
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError('Password must contain at least one special character')
    return password

# ==== USER MODELS ====

class UserBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    email: EmailStr
    upi_id: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[RoleType] = RoleType.borrower

    _validate_upi = validator('upi_id', allow_reuse=True)(validate_upi_id)

    @validator('phone')
    def validate_phone(cls, v):
        if v and not re.match(r'^\+?\d{10,15}$', v):
            raise ValueError("Invalid phone number format")
        return v

class UserCreate(UserBase):
    password: str
    _validate_password = validator('password', allow_reuse=True)(validate_password_strength)

class UserOut(UserBase):
    id: int
    is_verified: bool = False

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

# ==== LOAN MODELS ====

class LoanBase(BaseModel):
    lender_id: int
    borrower_id: int
    principal_amount: Decimal = Field(..., gt=0)
    interest_rate: Decimal = Field(default=0, ge=0, le=100)
    payment_frequency: PaymentFrequency = PaymentFrequency.monthly
    number_of_payments: int = Field(default=1, gt=0)
    description: Optional[str] = None

class LoanCreate(LoanBase):
    total_amount: Decimal = Field(..., gt=0)
    payment_amount: Decimal = Field(..., gt=0)
    start_date: datetime
    due_date: datetime

    @validator('due_date')
    def check_due_after_start(cls, due_date, values):
        if 'start_date' in values and due_date <= values['start_date']:
            raise ValueError("Due date must be after start date")
        return due_date

class LoanUpdate(BaseModel):
    status: Optional[LoanStatus] = None
    sub_status: Optional[LoanSubStatus] = None
    interest_rate: Optional[Decimal] = Field(None, ge=0, le=100)
    payment_frequency: Optional[PaymentFrequency] = None
    number_of_payments: Optional[int] = Field(None, gt=0)

class LoanResponse(BaseModel):
    id: int
    lender_id: int
    borrower_id: int
    principal_amount: Optional[Decimal]
    interest_rate: Optional[Decimal]
    payment_frequency: Optional[PaymentFrequency]
    number_of_payments: Optional[int]
    status: str
    sub_status: Optional[str] = None

    class Config:
        from_attributes = True

# ==== PAYMENT MODELS ====

class PaymentCreate(BaseModel):
    loan_id: int
    amount: Decimal = Field(..., gt=0)
    due_date: date
    payment_method: Optional[str] = None
    transaction_id: Optional[str] = None
    notes: Optional[str] = None

class PaymentResponse(BaseModel):
    id: int
    loan_id: int
    amount: Decimal
    status: PaymentStatus
    due_date: date
    paid_date: Optional[date]
    payment_method: Optional[str]
    transaction_id: Optional[str]
    principal_portion: Decimal
    interest_portion: Decimal
    late_fee: Decimal
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

# ==== NOTIFICATIONS ====

class NotificationCreate(BaseModel):
    user_id: int
    type: NotificationType
    channel: NotificationChannel
    title: str
    message: str
    loan_id: Optional[int] = None
    payment_id: Optional[int] = None
    scheduled_for: Optional[datetime] = None

class NotificationResponse(BaseModel):
    id: int
    user_id: int
    type: NotificationType
    channel: NotificationChannel
    title: str
    message: str
    is_read: bool
    is_sent: bool
    sent_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

# ==== DASHBOARDS ====

class BorrowerDashboard(BaseModel):
    active_loans: List[LoanResponse]
    pending_requests: List[LoanResponse]
    completed_loans_count: int
    total_borrowed: Decimal
    total_repaid: Decimal
    next_payment_due: Optional[PaymentResponse]

class LenderDashboard(BaseModel):
    active_loans: List[LoanResponse]
    pending_requests: List[LoanResponse]
    completed_loans_count: int
    total_lent: Decimal
    total_collected: Decimal
    overdue_payments: List[PaymentResponse]

# ==== SEARCH ====

class LoanSearchFilters(BaseModel):
    status: Optional[List[LoanStatus]] = None
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    lender_id: Optional[int] = None
    borrower_id: Optional[int] = None
    interest_rate_min: Optional[Decimal] = None
    interest_rate_max: Optional[Decimal] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    payment_frequency: Optional[PaymentFrequency] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class LoanSummary(BaseModel):
    id: int
    lender_id: int
    borrower_id: int
    principal_amount: float
    interest_rate: float
    total_amount: float
    payment_frequency: str
    number_of_payments: int
    payment_amount: float
    start_date: Optional[date]
    due_date: Optional[date]
    next_payment_date: Optional[date]
    status: LoanStatus
    sub_status: Optional[str]
    amount_paid: float
    amount_remaining: float
    description: Optional[str]
    created_at: Optional[date]
    updated_at: Optional[date]

class LoanSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    results: List[LoanSummary]

    class Config:
        from_attributes = True

# ==== AUTH / MISC ====

class RateLimitInfo(BaseModel):
    requests_remaining: int
    reset_time: datetime
    limit: int

class TokenRequest(BaseModel):
    refresh_token: str

class RoleUpdate(BaseModel):
    new_role: RoleType

class UpdateProfile(BaseModel):
    name: Optional[str] = None
    upi_id: Optional[str] = None
    phone: Optional[str] = None
    password: str

    _validate_upi_update = validator('upi_id', allow_reuse=True)(validate_upi_id)
    _validate_password_update = validator('password', allow_reuse=True)(validate_password_strength)

    @validator('phone')
    def validate_phone(cls, v):
        if v and not re.match(r'^\+?\d{10,15}$', v):
            raise ValueError("Invalid phone number format")
        return v

class ChangePassword(BaseModel):
    current_password: str
    new_password: str

    _validate_new_password = validator('new_password', allow_reuse=True)(validate_password_strength)

class EmailVerificationRequest(BaseModel):
    email: EmailStr

class EmailVerificationConfirm(BaseModel):
    token: str

class AuditLogOut(BaseModel):
    id: int
    user_id: int
    action: str
    description: Optional[str]
    loan_id: Optional[int]
    payment_id: Optional[int]
    ip_address: Optional[str]
    timestamp: datetime

class PaymentOut(BaseModel):
    id: int
    loan_id: int
    amount: float
    due_date: date
    status: str
    paid_date: Optional[date] = None
    txn_reference: Optional[str]
    principal_portion: float
    interest_portion: float
    late_fee: float
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class RepaymentRetryResponse(BaseModel):
    id: int
    payment_id: int
    attempted_at: datetime
    status: PaymentRetryStatus
    notes: Optional[str]

    class Config:
        from_attributes = True
