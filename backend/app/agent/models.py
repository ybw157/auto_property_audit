from pydantic import BaseModel, Field
from typing import Optional


class ContractMetadata(BaseModel):
    project_name: Optional[str] = Field(default=None, description="项目名称")
    business_type: Optional[str] = Field(default=None, description="业务类型（住宅/商业/物业/酒店/街区/写字楼等）")
    supplier: Optional[str] = Field(default=None, description="供应商/乙方名称")
    contract_no: Optional[str] = Field(default=None, description="合同编号")
    contract_name: Optional[str] = Field(default=None, description="合同名称/标题")
    service_type: Optional[str] = Field(default=None, description="服务类型（保洁/保安/其他）")
    version: Optional[str] = Field(default=None, description="版本号")
    start_date: Optional[str] = Field(default=None, description="合同开始日期 YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="合同结束日期 YYYY-MM-DD")


class DeductionRule(BaseModel):
    item_name: str = Field(description="扣款项目名称，如'违约金'、'物业费扣款'、'维修费'等")
    amount: Optional[str] = Field(default=None, description="扣款金额，可以是具体数字或计算公式")
    condition: Optional[str] = Field(default=None, description="触发扣款的条件，如'逾期超过30天'")
    standard: Optional[str] = Field(default=None, description="扣款标准或计算方式，如'按日千分之三'")
    clause_ref: Optional[str] = Field(default=None, description="引用的合同条款编号或名称")
    party_deducting: Optional[str] = Field(default=None, description="扣款方/收款方")
    party_deducted: Optional[str] = Field(default=None, description="被扣款方/付款方")
    effective_date: Optional[str] = Field(default=None, description="生效日期或时间段")
    remarks: Optional[str] = Field(default=None, description="补充说明")


class ContractRules(BaseModel):
    contract_title: Optional[str] = Field(default=None, description="合同标题")
    parties: list[str] = Field(default_factory=list, description="合同各方主体名称")
    effective_period: Optional[str] = Field(default=None, description="合同有效期")
    deduction_rules: list[DeductionRule] = Field(default_factory=list, description="扣款规则列表")
    total_amount: Optional[str] = Field(default=None, description="合同总金额")
    summary: Optional[str] = Field(default=None, description="合同内容摘要")


class LateEarlyTier(BaseModel):
    max_minutes: float = Field(description="该阶梯的最大分钟数，如30表示30分钟以内")
    deduction: float = Field(description="该阶梯的扣款金额（元）")
    description: Optional[str] = Field(default=None, description="阶梯说明，如'迟到或早退30分钟以内'")


class ContractAuditParams(BaseModel):
    late_early_tiers: Optional[list[LateEarlyTier]] = Field(default=None, description="迟到早退阶梯扣款")
    late_early_over_minutes_as_absence: Optional[float] = Field(default=None, description="迟到/早退超过N分钟算旷工")
    missing_clock_deduction: Optional[float] = Field(default=None, description="漏打卡每次扣款金额（元）")
    missing_clock_free_times_per_month: Optional[float] = Field(default=None, description="每月漏打卡免扣次数")
    missing_clock_free_requires_attendance_proof: Optional[bool] = Field(default=None, description="免扣是否需要出勤证明")
    contract_deduction_coefficient: Optional[float] = Field(default=None, description="合同扣款系数")
    attendance_deduction_coefficient: Optional[float] = Field(default=None, description="考勤扣款系数")
    late_grace_minutes: Optional[float] = Field(default=None, description="迟到宽限分钟数")
    early_leave_grace_minutes: Optional[float] = Field(default=None, description="早退宽限分钟数")
    required_clock_count: Optional[float] = Field(default=None, description="每日要求打卡次数")
    minimum_work_hour_ratio: Optional[float] = Field(default=None, description="最低工时比")
    single_person_daily_cap: Optional[float] = Field(default=None, description="单人单日扣款上限（元）")
    raw_deduction_text: Optional[str] = Field(default=None, description="合同中扣款条款原文摘录（留底备查）")