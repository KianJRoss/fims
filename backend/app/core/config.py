from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://fims:fims@localhost:5432/fims"
    REDIS_URL: str = "redis://localhost:6379/0"
    SECRET_KEY: str = "dev-secret-key"
    ENVIRONMENT: str = "development"
    MEDIA_ROOT: str = "./media"
    EMAIL_ENCRYPTION_KEY: str | None = None
    RECEIPT_PRINTER_HOST: str = ""
    RECEIPT_PRINTER_PORT: int = 9100

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]


settings = Settings()
