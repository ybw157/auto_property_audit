"""审核结果控制器。"""
from fastapi import APIRouter, Request, Body

from app.api.v2.core.result import Result
from app.api.v2.core.permissions import get_current_user, resolve_project_name
from app.api.v2.service.audit_result_service import (
    get_audit_result,
    list_audit_results,
    start_audit,
    confirm_audit,
    update_audit_result,
    confirm_exceptions,
    finalize_audit,
)
from app.api.v2.dto.requests import AuditResultUpdateRequest, BatchConfirmRequest

router = APIRouter()


@router.get("/audit-results")
def get_results(
    request: Request,
    project_name: str = "",
    audit_month: str = "",
):
    """获取审核结果列表。"""
    project_name = resolve_project_name(request, project_name)
    data = list_audit_results(project_name, audit_month)
    return Result.ok(data=data)


@router.get("/audit-results/detail")
def get_result_detail(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
):
    """获取审核结果详情。"""
    project_name = resolve_project_name(request, project_name)
    data = get_audit_result(project_name, business_type, audit_month)
    return Result.ok(data=data)


@router.post("/audit-results/start")
def start_audit_endpoint(
    request: Request,
    project_name: str = Body(..., description="项目名称"),
    business_type: str = Body(..., description="业态"),
    audit_month: str = Body(..., description="审核月份，如 202607"),
):
    """开始审核。"""
    project_name = resolve_project_name(request, project_name)
    return start_audit(project_name, business_type, audit_month)

@router.post("/audit-results/confirm")
def confirm_audit_endpoint(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
):
    """确认审核结果。"""
    current = get_current_user(request)
    project_name = resolve_project_name(request, project_name)
    data = confirm_audit(project_name, business_type, audit_month, current["username"])
    return Result.ok(data=data)


@router.put("/audit-results/update")
def update_audit_result_endpoint(
    request: Request,
    body: AuditResultUpdateRequest,
):
    get_current_user(request)
    data = update_audit_result(
        project_name=resolve_project_name(request, body.project_name),
        business_type=body.business_type,
        audit_month=body.audit_month,
        results_json=body.results_json,
        summary_json=body.summary_json,
        status=body.status,
    )
    return Result.ok(data=data, message="审核结果更新成功")


@router.put("/audit-results/confirm-exceptions")
def confirm_exceptions_endpoint(
    request: Request,
    body: BatchConfirmRequest,
):
    """批量确认异常记录。"""
    current = get_current_user(request)
    data = confirm_exceptions(
        project_name=resolve_project_name(request, body.project_name),
        business_type=body.business_type,
        audit_month=body.audit_month,
        confirmed_records=[r.model_dump() for r in body.confirmed_records],
        confirmed_by=current["username"],
    )
    return Result.ok(data=data, message=data["message"])


@router.post("/audit-results/finalize")
def finalize_audit_endpoint(
    request: Request,
    project_name: str = Body(..., description="项目名称"),
    business_type: str = Body(..., description="业态"),
    audit_month: str = Body(..., description="审核月份"),
):
    """确认最终版：计算最终扣款并锁定审核结果。"""
    current = get_current_user(request)
    data = finalize_audit(
        project_name=resolve_project_name(request, project_name),
        business_type=business_type,
        audit_month=audit_month,
        confirmed_by=current["username"],
    )
    return Result.ok(data=data, message=data["message"])
