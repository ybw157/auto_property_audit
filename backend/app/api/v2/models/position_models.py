from __future__ import annotations
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, JSON, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


@dataclass
class ScheduleSlot:
    """排班槽位 —— 挂在 Position 下，代表一个必须被填满的岗位名额。

    同名岗位按 area 区分不同槽位，每个槽位每天排班人可能不同。
    daily: {日期: [单元格字典]}，单元格含 names(上班人) 和 status(出勤/休息/请假)。
    """
    area: str = ""                 # 固定区域/工作区域，同名岗位靠此区分不同槽位
    slot_index: int = 0            # 同一岗位内的序号，从 1 开始
    daily: dict = field(           # {日期: [单元格字典]}；单元格由 classify_schedule_cell 产出
        default_factory=dict,
    )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleSlot":
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class Position:
    position_name: str = "" #岗位名称
    position_type: str = "" #职位归属
    staff_list: list[str] = field(default_factory=list) #员工列表
    shift_time: str = "" #班次时间
    daily_hours: float = 0.0 #单岗日时长
    monthly_hours: float = 0.0 # 单岗位月总时长
    hourly_rate: float = 0.0 # 工时单价
    monthly_total: float = 0.0 #月度合价
    actual_count: int = 0 #实际人数
    mid_clock_time: str = "" #中班打卡时间
    is_cross_midnight: bool = False #是否跨 midnight
    slots: list[ScheduleSlot] = field(default_factory=list) #排班槽位列表

    def to_dict(self) -> dict:
        data = asdict(self)
        slots_data = []
        for s in self.slots:
            try:
                slots_data.append(asdict(s) if hasattr(s, "__dataclass_fields__") else s)
            except Exception as e:
                print(f"[Position.to_dict] 序列化 slot 失败: {e}, slot={s}")
                slots_data.append({"error": str(e)})
        data["slots"] = slots_data
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Position":
        valid_fields = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        slots = [
            s if isinstance(s, ScheduleSlot) else ScheduleSlot.from_dict(s)
            for s in filtered.get("slots", [])
            if isinstance(s, (ScheduleSlot, dict))
        ]
        filtered["slots"] = slots
        return cls(**filtered)


class PositionInfo(Base):
    __tablename__ = "position_infos"
    __table_args__ = (UniqueConstraint("project_name", "business_type", "audit_month"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True) #主键
    project_name: Mapped[str] = mapped_column(String(255), nullable=False) #项目名称
    business_type: Mapped[str] = mapped_column(String(50), nullable=False) #业态
    supplier: Mapped[str] = mapped_column(String(255), nullable=False) #供应商
    audit_month: Mapped[str] = mapped_column(String(10), default="") #审核月份
    contracted_count: Mapped[int] = mapped_column(Integer, default=0) #合同人数
    actual_count: Mapped[int] = mapped_column(Integer, default=0) #实际人数
    positions_json: Mapped[list] = mapped_column(JSON, nullable=False) #岗位json
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now()) #创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now() #更新时间
    )

    positions: list[Position] = []

    def to_dict(self) -> dict:
        data = {c.name: getattr(self, c.name) for c in self.__table__.columns.values()}
        # positions_json 是数据库存储的岗位详情 JSON，直接返回
        # positions 是内存中的 ORM 关系，不暴露给前端
        return data
