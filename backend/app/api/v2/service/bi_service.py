"""BI 考勤数据导入服务 — 同步导入。"""
import os

from app.api.v2.core.config import settings
from app.api.v2.dao.bi_dao import save_bi_records
from app.api.v2.utils.excel_attendance_parser import parse_attendance_excel


def import_bi_excel(bi_month: str, file_content: bytes, project_name: str = "") -> dict:
    """
    同步导入 BI 考勤 Excel 文件。

    :param bi_month: BI 考勤月份，如 "202608"
    :param file_content: Excel 文件内容（bytes）
    :param project_name: 登录用户所属项目名，用于过滤只导入该项目的记录
    :return: 导入结果 {"count": int, "message": str}
    """
    settings.bi_dir.mkdir(parents=True, exist_ok=True)
    file_path = str(settings.bi_dir / f"attendance_{bi_month}.xlsx")
    with open(file_path, "wb") as f:
        f.write(file_content)

    # 去掉项目名称中的"项目"二字，保持数据一致性
    project_name = project_name.replace("项目", "") if project_name else ""

    try:
        # 如果指定了项目名，只导入该项目的记录
        filter_project = project_name if project_name else None
        records = parse_attendance_excel(file_path, bi_month, filter_project=filter_project)

        if not records:
            return {
                "count": 0,
                "message": "未找到匹配的考勤记录" + (f"（项目：{project_name}）" if project_name else ""),
            }

        count = save_bi_records(bi_month, records)
        return {
            "count": count,
            "message": f"导入成功，共 {count} 条记录" + (f"（项目：{project_name}）" if project_name else ""),
        }
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
