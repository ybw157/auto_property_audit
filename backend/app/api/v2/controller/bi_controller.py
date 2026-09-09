"""BI 考勤数据控制器。"""
from typing import Any

from fastapi import APIRouter, UploadFile, File, Query, Request, HTTPException

from app.api.v2.core.result import Result
from app.api.v2.dao.bi_dao import get_bi_upload_history
from app.api.v2.service.bi_service import import_bi_excel

router = APIRouter()


def get_current_user(request: Request) -> Any:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


@router.get("/bi/history")
async def get_bi_history(request: Request):
    """获取 BI 考勤上传历史记录。"""
    get_current_user(request)
    history = get_bi_upload_history()
    return Result.ok(data=history)


@router.post("/bi/upload")
async def upload_bi_excel(
    request: Request,
    file: UploadFile = File(...),
    bi_month: str = Query(..., description="BI 考勤月份，如 202608"),
):
    """
    上传 BI 考勤 Excel 文件。

    自动从登录用户信息中获取所属项目，只导入该项目的考勤记录。
    集团管理员（role=True）可导入所有项目数据。
    """
    user = get_current_user(request)
    is_admin = user.get("role", False)
    project_name = user.get("project_name", "") if not is_admin else ""

    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        return Result.fail(message="仅支持 .xlsx 或 .xls 格式的 Excel 文件")

    content = await file.read()
    result = import_bi_excel(bi_month, content, project_name=project_name)
    return Result.ok(data=result, message=result["message"])
