"""审核结果控制器。"""
from fastapi import APIRouter, Request, Body

from app.api.v2.core.result import Result
from app.api.v2.core.permissions import get_current_user, resolve_project_name
from app.api.v2.service.audit_result_service import (
    get_audit_result,
    list_audit_results,
    start_audit,
    update_audit_result,
    confirm_exceptions,
)
from app.api.v2.dto.requests import AuditResultUpdateRequest, BatchConfirmRequest

router = APIRouter()


@router.get("/audit-results")
def get_results(
    request: Request,
    project_name: str = "",
    audit_month: str = "",
    business_type: str = "",
):
    """获取审核结果列表（可按业态收窄，前端据此去重出服务类型导航）。"""
    project_name = resolve_project_name(request, project_name)
    data = list_audit_results(project_name, audit_month, business_type)
    return Result.ok(data=data)


@router.get("/audit-results/detail")
def get_result_detail(
    request: Request,
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str = "",
):
    """获取审核结果详情（service_type 为定位键第四列，必填）。"""
    project_name = resolve_project_name(request, project_name)
    data = get_audit_result(project_name, business_type, audit_month, service_type)
    return Result.ok(data=data)


@router.post("/audit-results/start")
def start_audit_endpoint(
    request: Request,
    project_name: str = Body(..., description="项目名称"),
    business_type: str = Body(..., description="业态"),
    audit_month: str = Body(..., description="审核月份，如 202607"),
    service_type: str = Body("", description="服务类型（保安/保洁），必填"),
):
    """开始审核。"""
    project_name = resolve_project_name(request, project_name)
    return start_audit(project_name, business_type, audit_month, service_type)

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
        service_type=body.service_type,
    )
    return Result.ok(data=data, message="审核结果更新成功")


@router.put("/audit-results/confirm-exceptions")
def confirm_exceptions_endpoint(
    request: Request,
    body: BatchConfirmRequest,
):
    """批量确认异常记录（就地修改该审核结果并标记为唯一最终版）。"""
    current = get_current_user(request)
    data = confirm_exceptions(
        project_name=resolve_project_name(request, body.project_name),
        business_type=body.business_type,
        audit_month=body.audit_month,
        confirmed_records=[r.model_dump() for r in body.confirmed_records],
        confirmed_by=current["username"],
        service_type=body.service_type,
    )
    return Result.ok(data=data, message=data["message"])
