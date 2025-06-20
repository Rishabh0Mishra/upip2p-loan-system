from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    # Database
    db_user: str = Field(..., alias="DB_USER")
    db_password: str = Field(..., alias="DB_PASSWORD")
    db_host: str = Field(..., alias="DB_HOST")
    db_name: str = Field(..., alias="DB_NAME")

    # SendGrid (Email)
    sendgrid_key: str = Field(..., alias="SENDGRID_KEY")
    email_from: str = Field(..., alias="EMAIL_FROM")

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

    # NSDL eSign
    use_nsdl_mock: bool = Field(False, alias="USE_NSDSL_MOCK")
    nsdl_esign_base_url: str = Field("https://api.nsdl.co.in/esign/v1", alias="NSDL_ESIGN_BASE_URL")
    nsdl_api_key: str = Field("your_nsdl_api_key", alias="NSDL_API_KEY")
    nsdl_secret_key: str = Field("your_nsdl_secret_key", alias="NSDL_SECRET_KEY")

    @property
    def database_url(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}/{self.db_name}"

    class Config:
        env_file = ".env"
        case_sensitive = True
        populate_by_name = True

settings = Settings()
