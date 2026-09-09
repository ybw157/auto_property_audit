"""请求 DTO — 定义接口入参格式。"""
from pydantic import BaseModel
from typing import Optional


# ========== 认证 ==========
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


# ========== 审核批次 ==========
class AuditBatchCreateRequest(BaseModel):
    project_name: str = ""
    project_code: str = ""
    audit_month: str = ""
    business_type: str = ""


# ========== 配置 ==========
class ConfigUpdateRequest(BaseModel):
    value: str


# ========== 合同 ==========
class ManualRulesUpdateRequest(BaseModel):
    """手动填写扣款细则"""
    late_early_tiers: Optional[list[dict]] = None
    late_early_over_minutes_as_absence: Optional[float] = None
    missing_clock_deduction: Optional[float] = None
    missing_clock_free_times_per_month: Optional[float] = None
    missing_clock_free_requires_attendance_proof: Optional[bool] = None
    contract_deduction_coefficient: Optional[float] = None
    single_person_daily_cap: Optional[float] = None


class RuleCenterUpdateRequest(BaseModel):
    rules: dict


class RuleCenterStatusUpdateRequest(BaseModel):
    status: str = "已确认"


# ========== 合同文件 ==========
class ContractRulesUpdateRequest(BaseModel):
    rules: list


class ContractStatusUpdateRequest(BaseModel):
    is_active: bool


# ========== 审核结果 ==========
class AttendanceProofUpdateRequest(BaseModel):
    """更新单条漏打卡记录的出勤证明状态"""
    employee_name: str
    work_date: str
    has_proof: bool


class ConfirmRecordRequest(BaseModel):
    """单条异常记录确认"""
    employee_name: str
    work_date: str
    exception_type: str = "missing_clock"
    confirmed: bool
    confirm_note: str = ""
    free_deduction: bool = False


class BatchConfirmRequest(BaseModel):
    """批量确认异常记录"""
    project_name: str
    business_type: str
    audit_month: str
    confirmed_records: list[ConfirmRecordRequest]
    confirmed_by: str = ""


# ========== 岗位信息更新 ==========
class PositionInfoUpdateRequest(BaseModel):
    """审核员修改岗位信息（不含排班槽位 ScheduleSlot）"""
    project_name: str
    business_type: str
    audit_month: str
    supplier: Optional[str] = None
    contracted_count: Optional[int] = None
    actual_count: Optional[int] = None
    positions_json: Optional[list[dict]] = None


# ========== 合同文件更新 ==========
class ContractUpdateRequest(BaseModel):
    """审核员修改合同解析后的字段"""
    project_name: Optional[str] = None
    business_type: Optional[str] = None
    supplier: Optional[str] = None
    contract_no: Optional[str] = None
    contract_name: Optional[str] = None
    service_type: Optional[str] = None
    version: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rules: Optional[dict] = None


# ========== 审核结果更新 ==========
class AuditResultUpdateRequest(BaseModel):
    """审核员修改审核结果"""
    project_name: str
    business_type: str
    audit_month: str
    results_json: Optional[list] = None
    summary_json: Optional[list] = None
    status: Optional[str] = None
