from __future__ import annotations
from dataclasses import dataclass, asdict, field
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, func, JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .position_models import ScheduleSlot


@dataclass
class ContractStaffing:
    position: str
    position_normalized: str = ""
    business_type: str = ""
    area: str = ""
    contract_headcount: int = 0
    staff_names: str = ""
    hourly_rate: float = 0
    service_type: str = ""
    slots: list[ScheduleSlot] = field(default_factory=list)

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("slots", None)
        return data


class ContractRecord(Base):
    __tablename__ = "contract"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True) #主键
    project_name: Mapped[str] = mapped_column(String(255), nullable=False) #项目名称
    business_type: Mapped[str] = mapped_column(String(50), nullable=False) #业务类型
    supplier: Mapped[str] = mapped_column(String(255), default="") #供应商
    contract_no: Mapped[str] = mapped_column(String(255), default="") #合同编号
    contract_name: Mapped[str] = mapped_column(String(255), default="") #合同名称
    service_type: Mapped[str] = mapped_column(String(50), default="") #服务类型
    version: Mapped[str] = mapped_column(String(50), default="") #版本
    start_date: Mapped[str] = mapped_column(String(30), default="") #开始日期
    end_date: Mapped[str] = mapped_column(String(30), default="") #结束日期
    original_name: Mapped[str] = mapped_column(String(500), nullable=False) #原始文件名
    file_format: Mapped[str] = mapped_column(String(20), nullable=False) #文件格式
    storage_path: Mapped[str] = mapped_column(String(1000), nullable=False) #存储路径
    rules: Mapped[dict | list] = mapped_column(JSON, default=dict) #规则json
    extract_status: Mapped[str] = mapped_column(String(20), default="pending") #提取状态
    status: Mapped[str] = mapped_column(String(20), default="active") #状态
    is_active: Mapped[int] = mapped_column(Integer, default=1) #是否启用
    is_deleted: Mapped[int] = mapped_column(Integer, default=0) #是否删除：0未删除，1已删除
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now()) #创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now() #更新时间
    )