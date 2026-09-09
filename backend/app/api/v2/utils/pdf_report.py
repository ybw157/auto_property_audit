"""V2 PDF 报告生成器（旧版样式迁移层）。

本文件不再自行实现报告排版，而是把新流水线数据交给 report_adapter 适配成
旧版 pdf_report_old 所需的 results 结构，再调用旧版函数生成 PDF，确保报告
的样式与逻辑与旧版代码仓完全一致：

  - build_attendance_detail_pdf  → 旧版 build_attendance_base_pdf   （考勤明细：打卡列含实际 BI 考勤）
  - build_deduction_report_pdf   → 旧版 build_deduction_pdf         （扣款金额报告，对应截图样式）
  - build_summary_report_pdf     → 旧版 build_combined_report_pdf   （AI 审核汇总与扣款报告，对应桌面 PDF 样式）
"""
from __future__ import annotations

from pathlib import Path

from app.api.v2.utils.pdf_report_old import (
    build_attendance_base_pdf,
    build_combined_report_pdf,
    build_deduction_pdf,
)
from app.api.v2.utils.report_adapter import adapt_to_old_results


def build_attendance_detail_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    bi_records: list[dict],
    position_data: list[dict],
    report_dir: Path,
    audit_results: dict | None = None,
    contract: dict | None = None,
) -> dict:
    """考勤明细 PDF —— 旧版 build_attendance_base_pdf 样式。
    打卡列展示实际 BI 考勤记录。"""
    results = adapt_to_old_results(
        project_name=project_name,
        business_type=business_type,
        audit_month=audit_month,
        bi_records=bi_records,
        position_data=position_data,
        audit_results=audit_results,
        contract=contract,
        kind="attendance",
    )
    return build_attendance_base_pdf(0, report_dir, results)


def build_deduction_report_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    results_data: dict,
    report_dir: Path,
    contract: dict | None = None,
) -> dict:
    """扣款金额报告 PDF —— 旧版 build_deduction_pdf 样式（对应截图）。"""
    results = adapt_to_old_results(
        project_name=project_name,
        business_type=business_type,
        audit_month=audit_month,
        audit_results=results_data,
        contract=contract,
        kind="deduction",
    )
    return build_deduction_pdf(0, report_dir, results)


def build_summary_report_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    results_data: dict,
    report_dir: Path,
    contract: dict | None = None,
) -> dict:
    """AI 审核汇总与扣款报告 PDF —— 旧版 build_combined_report_pdf 样式（对应桌面 PDF）。"""
    results = adapt_to_old_results(
        project_name=project_name,
        business_type=business_type,
        audit_month=audit_month,
        audit_results=results_data,
        contract=contract,
        kind="combined",
    )
    return build_combined_report_pdf(0, report_dir, results)
