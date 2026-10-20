"""集团驾驶舱控制器。"""
from fastapi import APIRouter, Request

from app.api.v2.core.permissions import get_current_user, is_admin, resolve_project_name_for
from app.api.v2.core.result import Result
from app.api.v2.service.dashboard_service import group_summary, project_summary

router = APIRouter()


@router.get("/dashboard/group-summary")
def get_group_summary(
    request: Request,
    audit_month: str = "",
):
    """集团管理员驾驶舱汇总（仅集团管理员可访问）。"""
    user = get_current_user(request)
    if not is_admin(user):
        return Result.fail(message="无权访问集团驾驶舱").to_dict()
    data = group_summary(audit_month)
    return Result.ok(data=data)


@router.get("/dashboard/project-summary")
def get_project_summary(
    request: Request,
    project_name: str = "",
):
    """项目账号驾驶舱汇总：仅统计本项目已确认的最终版数据。"""
    user = get_current_user(request)
    proj = resolve_project_name_for(user, project_name)
    if not proj:
        return Result.fail(message="当前账号未绑定项目，无法查看项目驾驶舱").to_dict()
    data = project_summary(proj)
    return Result.ok(data=data)
