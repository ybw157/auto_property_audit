"""PDF 报告控制器。"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.v2.core.config import settings
from app.api.v2.core.result import Result
from app.api.v2.core.database import json_loads, now_text
from app.api.v2.core.permissions import resolve_project_name
from app.api.v2.dao import audit_result_dao, bi_dao, position_dao, report_dao, contract_dao
from app.api.v2.utils.pdf_report import (
    build_attendance_detail_pdf,
    build_summary_report_pdf,
)

router = APIRouter()


@router.get("/reports")
def list_reports(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
):
    project_name = resolve_project_name(request, project_name)
    # 只展示已确认（locked）审核的报告：未确认的审核不出报告，避免看到草稿版
    ar = audit_result_dao.get_audit_result(project_name, business_type, audit_month)
    if not (ar and getattr(ar, "locked", 0)):
        return Result.ok(data=[])
    reports = report_dao.list_reports(project_name, business_type, audit_month)
    return Result.ok(data=reports)


@router.post("/reports/generate")
def generate_report(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
    report_type: str,
):
    project_name = resolve_project_name(request, project_name)
    if report_type not in ("attendance", "summary"):
        raise HTTPException(status_code=400, detail="无效的报告类型")

    audit_result = audit_result_dao.get_audit_result(project_name, business_type, audit_month)
    if not audit_result:
        raise HTTPException(status_code=404, detail="未找到审核结果")
    if not getattr(audit_result, "locked", 0):
        raise HTTPException(
            status_code=400,
            detail="审核尚未确认，无法生成报告，请先在审核页确认最终版（确认/锁定）后再生成",
        )

    report_dir = settings.report_dir / project_name
    report_dir.mkdir(parents=True, exist_ok=True)

    # 取启用中的合同，用于报告头部的合同编号/供应商/合同名称
    contract = None
    contracts = contract_dao.get_contracts(project_name, business_type)
    for c in contracts:
        if getattr(c, "is_active", 0):
            contract = {
                "contract_no": getattr(c, "contract_no", ""),
                "supplier": getattr(c, "supplier", ""),
                "contract_name": getattr(c, "contract_name", "未匹配"),
            }
            break
    if contract is None and contracts:
        c = contracts[0]
        contract = {
            "contract_no": getattr(c, "contract_no", ""),
            "supplier": getattr(c, "supplier", ""),
            "contract_name": getattr(c, "contract_name", "未匹配"),
        }

    results_data = json_loads(audit_result.results_json, {})

    if report_type == "attendance":
        bi_records = bi_dao.get_bi_by_project(audit_month, project_name)
        position_info = position_dao.get_position_info(project_name, business_type, audit_month)
        if not position_info:
            raise HTTPException(status_code=400, detail="未找到岗位数据")
        position_data = [p.to_dict() for p in position_info.positions]
        report_info = build_attendance_detail_pdf(
            project_name, business_type, audit_month, bi_records, position_data, report_dir, results_data, contract
        )
    elif report_type == "summary":
        report_info = build_summary_report_pdf(
            project_name, business_type, audit_month, results_data, report_dir, contract
        )

    report_id = report_dao.save_report(
        project_name=project_name,
        business_type=business_type,
        audit_month=audit_month,
        report_type=report_info["report_type"],
        file_format=report_info["file_format"],
        file_path=report_info["file_path"],
        created_at=str(now_text()),
    )

    return Result.ok(data={"id": report_id, **report_info}, message="报告生成成功")


@router.get("/reports/{report_id}/download")
def download_report(report_id: int):
    report = report_dao.get_report(report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")

    raw_path = report["file_path"].replace("\\", "/")
    file_path = Path(raw_path)
    if not file_path.is_absolute():
        file_path = settings.base_dir / file_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="报告文件不存在")

    return FileResponse(
        file_path,
        filename=file_path.name,
        media_type="application/pdf",
    )
