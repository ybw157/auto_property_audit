"""排班相关模型。"""
from dataclasses import dataclass, asdict, field
from typing import Any


@dataclass
class Shift:
    """班次标准。"""
    shift_name: str
    start_time: str
    end_time: str
    standard_hours: float = 8.0
    required_clock_count: int = 3
    clock_window: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Schedule:
    """一条排班记录。"""
    work_date: str
    employee_name: str
    position: str
    business_type: str = ""
    shift_name: str = ""
    schedule_type: str = "正常"
    original_position: str = ""
    original_employee_name: str = ""
    remark: str = ""
    source_row_no: Any = None

    def to_dict(self) -> dict:
        return asdict(self)
