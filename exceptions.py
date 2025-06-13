class LoanServiceException(Exception):
    """Base exception for loan service"""
    pass

class InsufficientFundsException(LoanServiceException):
    pass

class LoanNotEligibleException(LoanServiceException):
    pass

class InvalidLoanStateException(LoanServiceException):
    pass

class CreditLimitExceededException(LoanServiceException):
    pass

