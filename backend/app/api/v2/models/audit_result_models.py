from datetime import datetime
from sqlalchemy import String, Integer, DateTime, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditResult(Base):
    __tablename__ = "audit_results"
    __table_args__ = (UniqueConstraint("project_name", "business_type", "audit_month"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_type: Mapped[str] = mapped_column(String(50), nullable=False)
    audit_month: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="待审核")
    version: Mapped[int] = mapped_column(Integer, default=1)
    results_json: Mapped[list] = mapped_column(JSON, default=[])
    summary_json: Mapped[list] = mapped_column(JSON, default=[])
    ai_analysis: Mapped[str] = mapped_column(String(1000), default="")
    versions_json: Mapped[list] = mapped_column(JSON, default=[])
    logs_json: Mapped[list] = mapped_column(JSON, default=[])
    locked: Mapped[int] = mapped_column(Integer, default=0)
    confirmed_by: Mapped[str] = mapped_column(String(100), default="")
    confirmed_at: Mapped[str] = mapped_column(String(30), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )