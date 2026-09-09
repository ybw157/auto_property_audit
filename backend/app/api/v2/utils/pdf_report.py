"""V2 PDF 报告生成器（旧版样式迁移层）。

本文件不再自行实现报告排版，而是把新流水线数据交给 report_adapter 适配成
旧版 pdf_report_old 所需的 results 结构，再调用旧版函数生成 PDF，确保报告
的样式与逻辑与旧版代码仓完全一致：

  - build_attendance_detail_pdf  → 旧版 build_attendance_base_pdf   （考勤明细：打卡列含实际 BI 考勤）
  - build_summary_report_pdf     → 旧版 build_combined_report_pdf   （AI 审核汇总与扣款报告，对应桌面 PDF 样式）
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from app.api.v2.core.config import settings
from app.api.v2.utils.pdf_report_old import (
    build_attendance_base_pdf,
    build_combined_report_pdf,
)
from app.api.v2.utils.report_adapter import adapt_to_old_results


def _make_download_url(file_path: str | Path) -> str:
    """根据磁盘绝对路径推导 /files/... 静态访问 URL。

    后端将 settings.storage_dir 挂载为 /files，因此用 file_path 减去
    storage_dir 前缀即可得到相对 /files 的访问路径，并对含中文的
    目录/文件名做 URL 编码，保证可直接在浏览器或前端打开。
    """
    try:
        storage_root = Path(settings.storage_dir).resolve()
        rel = Path(file_path).resolve().relative_to(storage_root)
    except Exception:
        return ""
    encoded = "/".join(quote(part, safe="") for part in rel.parts)
    return f"/files/{encoded}"


def _finalize_report_info(info: dict, audit_month: str) -> dict:
    """把生成的报告文件名加上 audit_month（考勤明细_202608.pdf），

    重命名磁盘文件并同步 file_path 与 download_url，避免不同审核月份
    生成同名报告时互相覆盖（原文件名固定不含月份）。
    """
    old_path = Path(info["file_path"])
    new_path = old_path.with_name(f"{old_path.stem}_{audit_month}{old_path.suffix}")
    if new_path.exists():
        new_path.unlink()  # 同月重新生成时先删除旧文件
    old_path.rename(new_path)
    info["file_path"] = str(new_path)
    info["download_url"] = _make_download_url(new_path)
    return info


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
    info = build_attendance_base_pdf(0, report_dir, results)
    return _finalize_report_info(info, audit_month)


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
    info = build_combined_report_pdf(0, report_dir, results)
    return _finalize_report_info(info, audit_month)
