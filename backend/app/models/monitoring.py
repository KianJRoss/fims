from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AiMonitorConfig(Base):
    __tablename__ = "ai_monitor_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backend_type: Mapped[str] = mapped_column(String(20), nullable=False, default="api_key")
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="anthropic")
    encrypted_api_key: Mapped[str | None] = mapped_column(String(512))
    last_test_status: Mapped[str | None] = mapped_column(String(20))
    last_test_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
