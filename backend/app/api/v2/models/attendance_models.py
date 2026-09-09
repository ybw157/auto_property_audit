from dataclasses import dataclass, asdict, field
from datetime import datetime

from sqlalchemy import String, DateTime, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


@dataclass
class BiAttendanceRow:
    employee_name: str
    work_date: str
    clock_times: list[str] = field(default_factory=list)
    remark: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class BiAttendance(Base):
    __tablename__ = "bi_attendance"
    __table_args__ = (UniqueConstraint("bi_month", "employee_name", "employee_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bi_month: Mapped[str] = mapped_column(String(10), nullable=False)
    employee_name: Mapped[str] = mapped_column(String(100), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(100), default="")
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[str] = mapped_column(String(255), default="")
    attendance_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )