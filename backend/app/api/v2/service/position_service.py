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


def _extract_month_from_excel(file_path: Path) -> str:
    """从 Excel Sheet 名或内容中提取月份（文件名提取失败时的回退方案）。"""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(str(file_path), data_only=True, read_only=True)
        for name in wb.sheetnames:
            # 从 Sheet 名中匹配 "X月" 或 "XXXX年X月"
            m = re.search(r"(20\d{2})[-年._]?(\d{1,2})月?", name)
            if m:
                wb.close()
                return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"
            m = re.search(r"(\d{1,2})月", name)
            if m:
                wb.close()
                from datetime import datetime
                return f"{datetime.now().year}{int(m.group(1)):02d}"
        wb.close()
    except Exception:
        pass
    return ""


def upload_and_parse_excel(file: UploadFile, force_project_name: str = "") -> dict:
    """
    上传并解析项目岗位 Excel 表格，将结果存入数据库

    :param file: Excel 文件
    :param force_project_name: 强制使用的项目名（来自登录用户信息），非空时覆盖 Excel 解析出的项目名
    :return: 解析结果
    """
    filename = file.filename or ""

    # 保存到临时目录
    upload_dir = Path(settings.upload_dir) / "positions"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(file.file.read())

    # 先提取月份（YYYYMM），文件名失败时从 Excel Sheet 名提取
    audit_month = _extract_month_from_filename(filename)
    if not audit_month:
        audit_month = _extract_month_from_excel(file_path)
    bi_month = audit_month

    # 将月份转为 YYYY-MM 传给解析器，排班日期需要用它格式化
    audit_month_iso = f"{audit_month[:4]}-{audit_month[4:]}" if len(audit_month) == 6 else audit_month

    # 解析 Excel
    try:
        position_infos = parse_project_excel(file_path, audit_month=audit_month_iso)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{str(e)}")

    # 赋值月份并保存到数据库
    for info in position_infos:
        # 如果指定了 force_project_name，直接使用；否则使用 Excel 解析出的项目名（去掉"项目"二字）
        if force_project_name:
            info.project_name = force_project_name
        else:
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