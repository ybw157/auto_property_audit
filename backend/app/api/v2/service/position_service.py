"""岗位信息业务逻辑。"""
import re
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.api.v2.core.config import settings
from app.api.v2.dao import position_dao
from app.api.v2.utils.excel_project_parser import parse_project_excel


def _extract_month_from_filename(filename: str) -> str:
    """从文件名提取月份，格式 YYYYMM。"""
    match = re.search(r"(20\d{2})[-年._]?(\d{1,2})", filename)
    if match:
        return f"{int(match.group(1)):04d}{int(match.group(2)):02d}"
    match = re.search(r"(\d{1,2})[.月]", filename)
    if match:
        from datetime import datetime
        return f"{datetime.now().year}{int(match.group(1)):02d}"
    return ""


def upload_and_parse_excel(file: UploadFile) -> dict:
    """
    上传并解析项目岗位 Excel 表格，将结果存入数据库

    :param file: Excel 文件
    :return: 解析结果
    """
    filename = file.filename or ""

    # 保存到临时目录
    upload_dir = Path(settings.upload_dir) / "positions"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(file.file.read())

    # 解析 Excel
    try:
        position_infos = parse_project_excel(file_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{str(e)}")

    # 从文件名提取月份，格式 YYYYMM
    audit_month = _extract_month_from_filename(filename)
    bi_month = audit_month

    # 赋值月份并保存到数据库（去掉项目名称中的"项目"二字）
    for info in position_infos:
        info.project_name = info.project_name.replace("项目", "")
        info.audit_month = audit_month
        position_dao.save_position_info(info)

    return {
        "positions": [info.to_dict() for info in position_infos],
        "audit_month": audit_month,
        "bi_month": bi_month,
    }


def get_all_position_info() -> list[dict]:
    """
    获取所有岗位信息。

    :return: 岗位信息列表
    """
    infos = position_dao.get_all_position_info()
    return [info.to_dict() for info in infos]


def update_position_info(
    project_name: str,
    business_type: str,
    audit_month: str,
    supplier: str | None = None,
    contracted_count: int | None = None,
    actual_count: int | None = None,
    positions_json: list | None = None,
) -> dict:
    info = position_dao.get_position_info(project_name, business_type, audit_month)
    if not info:
        raise HTTPException(status_code=404, detail="未找到该岗位信息")
    position_dao.update_position_info(
        project_name, business_type, audit_month,
        supplier=supplier,
        contracted_count=contracted_count,
        actual_count=actual_count,
        positions_json=positions_json,
    )
    return {"message": "岗位信息更新成功", "project_name": project_name, "business_type": business_type, "audit_month": audit_month}