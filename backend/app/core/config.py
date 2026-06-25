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

    # Receipt content (FIMS' own ESC/POS receipt) -- safe to customize/iterate
    RECEIPT_STORE_NAME: str = "Bodigon Fireworks"
    RECEIPT_HEADER_LINES: str = "2740 US-6, Kendallville, IN 46755\n(260) 347-8595"  # centered under the store name
    RECEIPT_FOOTER: str = (
        "Thank you for shopping with us!\n"
        "All fireworks sales are final\n"
        "(260) 347-8595"
    )  # newline-separated lines printed before the cut

    # Payment terminal (Dejavoo Z-series over SPIn). Off by default so that, when
    # no terminal is present/configured, checkout behaves exactly as before.
    PAYMENT_TERMINAL_ENABLED: bool = False
    PAYMENT_TERMINAL_TRANSPORT: str = "serial"  # "serial" | "network"
    PAYMENT_TERMINAL_PORT: str = ""  # e.g. "COM5"; blank = auto-detect by USB VID/PID
    PAYMENT_TERMINAL_VID: int | None = None  # override; default Dejavoo/Castles 0x0CA6
    PAYMENT_TERMINAL_PID: int | None = None  # override; default 0xA050
    PAYMENT_TERMINAL_HOST: str = ""  # SPIn host when transport == "network"
    PAYMENT_TERMINAL_NET_PORT: int = 8080
    PAYMENT_TERMINAL_AUTH_KEY: str = ""  # SPIn Auth Key / Register ID (set in .env, never commit)

    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]


settings = Settings()
