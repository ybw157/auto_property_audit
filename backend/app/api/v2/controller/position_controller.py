"""岗位信息控制器。"""
from fastapi import APIRouter, UploadFile, File, HTTPException, Request

from app.api.v2.core.result import Result
from app.api.v2.core.permissions import resolve_project_name
from app.api.v2.dto.requests import PositionInfoUpdateRequest
from app.api.v2.service.position_service import (
    upload_and_parse_excel,
    get_all_position_info,
    update_position_info,
)

router = APIRouter()


@router.post("/positions/upload")
async def upload_position_excel(
    request: Request,
    file: UploadFile = File(...),

):
    """
    上传并解析项目岗位 Excel 表格。

    :param request: 请求对象（用于获取当前登录用户信息）
    :param file: Excel 文件（.xlsx）
    :return: 解析后的岗位信息列表
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    # 获取登录用户的项目名，强制覆盖 Excel 中解析出的项目名
    user_project_name = resolve_project_name(request, "")
    data = upload_and_parse_excel(file, force_project_name=user_project_name)

    return Result.ok(
        data={
            "project_name": data["positions"][0]["project_name"] if data["positions"] else user_project_name,
            "audit_month": data["audit_month"],
            "bi_month": data["bi_month"],
            "data":data
        },
        message="上传并解析成功",
    )


@router.get("/positions")
def get_positions():
    """
    获取所有岗位信息。

    :return: 岗位信息列表
    """
    data = get_all_position_info()
    return Result.ok(data=data, message="获取所有岗位信息成功")


@router.put("/positions/update")
def update_position(
    request: Request,
    body: PositionInfoUpdateRequest,
):
    data = update_position_info(
        project_name=resolve_project_name(request, body.project_name),
        business_type=body.business_type,
        audit_month=body.audit_month,
        supplier=body.supplier,
        contracted_count=body.contracted_count,
        actual_count=body.actual_count,
        positions_json=body.positions_json,
    )
    return Result.ok(data=data, message="岗位信息更新成功")
