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
    """从 Excel Sheet 名或内容中提取月份（文件名提取失败时的回退方案）。

    仅当调用方未显式传入审核月时才使用。注意 Sheet 名里的「X月」不含年份，
    此回退会补上当前年份，跨年上传时会得到错误月份，因此不能作为月份来源。
    """
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


def normalize_audit_month(value: str) -> str:
    """把审核月统一成 YYYYMM（兼容 '202608' / '2026-08' / '2026年8月'）。"""
    raw = str(value or "").strip()
    m = re.search(r"(20\d{2})[-年._/\s]?(\d{1,2})", raw)
    if m:
        return f"{int(m.group(1)):04d}{int(m.group(2)):02d}"
    m = re.search(r"^(\d{1,2})$", raw)
    if m:
        from datetime import datetime
        return f"{datetime.now().year}{int(m.group(1)):02d}"
    return ""


def upload_and_parse_excel(
    file: UploadFile,
    force_project_name: str = "",
    audit_month: str = "",
    service_type: str = "",
) -> dict:
    """
    上传并解析项目岗位 Excel 表格，将结果存入数据库

    :param file: Excel 文件
    :param force_project_name: 强制使用的项目名（来自登录用户信息），非空时覆盖 Excel 解析出的项目名
    :param audit_month: 审核月，来自 AI 审核页「选择审核月」控件（YYYYMM / YYYY-MM 均可）。
                        为唯一月份来源：同时用于库表定位与表内排班日期，
                        不再从文件名或 Sheet 名推断（Sheet 名缺月份时会导致月份为空、
                        与审核时读取的月份对不上，岗位因此无法被识别）。
                        未传入时才回退到文件名 / Sheet 名推断（兼容旧调用方）。
    :param service_type: 服务类型（保安/保洁），来自 AI 审核页「选择服务类型」控件。
                         不使用任何默认值或硬编码，原样写入 PositionInfo.service_type。
    :return: 解析结果
    """
    filename = file.filename or ""

    # 保存到临时目录
    upload_dir = Path(settings.upload_dir) / "positions"
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / filename
    file_path.write_bytes(file.file.read())

    # 月份来源统一为调用方传入的审核月；仅在未传入时才回退推断
    audit_month = normalize_audit_month(audit_month)
    if not audit_month:
        audit_month = _extract_month_from_filename(filename)
    if not audit_month:
        audit_month = _extract_month_from_excel(file_path)
    bi_month = audit_month

    # 将月份转为 YYYY-MM 传给解析器，排班日期需要用它格式化
    audit_month_iso = f"{audit_month[:4]}-{audit_month[4:]}" if len(audit_month) == 6 else audit_month

    # 解析 Excel
    try:
        position_infos = parse_project_excel(
            file_path,
            audit_month=audit_month_iso,
            service_type=service_type,
            force_project_name=force_project_name,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Excel 解析失败：{str(e)}")

    # 赋值月份、服务类型并保存到数据库
    for info in position_infos:
        # 项目名称一律取自登录用户（force_project_name），不使用 Excel 内解析出的项目名
        info.project_name = force_project_name
        info.audit_month = audit_month
        info.service_type = service_type or ""
        position_dao.save_position_info(info)

    return {
        "positions": [info.to_dict() for info in position_infos],
        "audit_month": audit_month,
        "bi_month": bi_month,
        "service_type": service_type or "",
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