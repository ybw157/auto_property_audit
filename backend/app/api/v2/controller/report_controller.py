"""PDF 报告控制器。"""
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.v2.core.config import settings
from app.api.v2.core.result import Result
from app.api.v2.core.database import json_loads, now_text
from app.api.v2.core.permissions import resolve_project_name
from app.api.v2.core.validators import require_service_type
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
    reports = report_dao.list_reports(project_name, business_type, audit_month)
    return Result.ok(data=reports)


@router.post("/reports/generate")
def generate_report(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
    report_type: str,
    service_type: str = "",
):
    project_name = resolve_project_name(request, project_name)
    if report_type not in ("attendance", "summary"):
        raise HTTPException(status_code=400, detail="无效的报告类型")

    # 报告按服务类型（保安 / 保洁）各自独立成文，不合并、不跨类型取数。
    # 服务类型是定位键的第四列，必填：缺失时直接报「缺少「服务类型」字段数据」，
    # 不做分支判断、不回退到空值或另一类服务的审核结果。
    # 校验通过后按该服务类型查出审核结果（audit_results 已按 service_type 分行存储），
    # 组装为 [{"service_type": st, "results": rd}] 交给报告生成器，
    # 由其生成一份带服务类型前缀的 PDF：
    #   保安考勤明细_202608.pdf / 保安AI审核汇总与扣款报告_202608.pdf
    service_type = require_service_type(service_type)
    audit_results = audit_result_dao.list_audit_results(
        project_name, audit_month, business_type, service_type
    )
    audit_input = []
    for ar in audit_results:
        raw = ar.results_json
        if not raw:
            continue
        rd = json_loads(raw, {}) if isinstance(raw, str) else raw
        if rd:
            audit_input.append({"service_type": ar.service_type, "results": rd})
    if not audit_input:
        raise HTTPException(status_code=404, detail=f"未找到「{service_type}」的审核结果")

    report_dir = settings.report_dir / project_name

    try:
        if report_type == "attendance":
            report_infos = build_attendance_detail_pdf(
                project_name, business_type, audit_month, audit_input, report_dir
            )
        else:
            report_infos = build_summary_report_pdf(
                project_name, business_type, audit_month, audit_input, report_dir
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    created = []
    for report_info in report_infos:
        report_id = report_dao.save_report(
            project_name=project_name,
            business_type=business_type,
            audit_month=audit_month,
            report_type=report_info["report_type"],
            file_format=report_info["file_format"],
            file_path=report_info["file_path"],
            created_at=str(now_text()),
        )
        created.append({"id": report_id, **report_info})

    types_text = "、".join(r["service_type"] for r in report_infos)
    return Result.ok(data=created, message=f"{types_text}报告生成成功")


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
