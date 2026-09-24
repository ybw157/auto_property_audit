"""岗位信息控制器。"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request

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
    file: UploadFile = File(..., description="岗位编制表 Excel 文件（.xlsx）"),
    project_name: str = Form("", description="项目名称（管理员可显式指定；普通账号忽略，强制用登录绑定项目）"),
    audit_month: str = Form("", description="审核月，来自 AI 审核页「选择审核月」（YYYY-MM 或 YYYYMM）"),
    service_type: str = Form("", description="服务类型（保安/保洁），必填，来自 AI 审核页「选择服务类型」"),
):
    """
    上传并解析项目岗位 Excel 表格。

    :param request: 请求对象（用于获取当前登录用户信息）
    :param file: Excel 文件（.xlsx）
    :param project_name: 管理员显式指定的项目名称（普通账号忽略）
    :param audit_month: AI 审核页「选择审核月」选中值
    :param service_type: AI 审核页「选择服务类型」选中值（必填）
    :return: 解析后的岗位信息列表
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")
    # 项目名唯一来源是登录用户身份（普通账号强制取其绑定项目，管理员为显式传入值）。
    # Excel 内的「项目名称」列已不再解析，因此这里拿到空值只可能是账号未绑定项目且未指定。
    user_project_name = resolve_project_name(request, project_name)
    data = upload_and_parse_excel(
        file,
        project_name=user_project_name,
        audit_month=audit_month,
        service_type=service_type,
    )

    return Result.ok(
        data={
            "project_name": user_project_name,
            "audit_month": data["audit_month"],
            "bi_month": data["bi_month"],
            "service_type": data["service_type"],
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
        service_type=body.service_type,
    )
    return Result.ok(data=data, message="岗位信息更新成功")
