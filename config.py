# config.py

from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Database
    db_user: str = Field(..., alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    db_host: str = Field(..., alias="DB_HOST")
    db_name: str = Field(..., alias="DB_NAME")

    # SMTP (Email)
    smtp_host: str = Field(..., alias="SMTP_HOST")
    smtp_port: int = Field(..., alias="SMTP_PORT")
    smtp_user: str = Field(..., alias="SMTP_USER")
    smtp_password: str = Field(..., alias="SMTP_PASSWORD")

    # JWT
    jwt_secret_key: str = Field(..., alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(..., alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(..., alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(..., alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # Business Rules
    max_loan_amount: float = Field(..., alias="MAX_LOAN_AMOUNT")
    min_loan_amount: float = Field(..., alias="MIN_LOAN_AMOUNT")

    # App
    environment: str = Field(..., alias="ENVIRONMENT")
    debug: bool = Field(..., alias="DEBUG")

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}/{self.db_name}"

    class Config:
        env_file = ".env"
        case_sensitive = True
        populate_by_name = True

settings = Settings()
