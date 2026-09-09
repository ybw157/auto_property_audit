"""BI 考勤 Excel 解析模块。

解析 BI 考勤 Excel 文件，输出与 BI 爬虫相同格式的数据。
支持从组织路径中解析标准项目名（使用 BI 映射表）。
"""
import re

import openpyxl

from app.api.v2.utils.bi_mapping import resolve_project_from_bi_path


def parse_attendance_excel(
    file_path: str,
    bi_month: str,
    filter_project: str | None = None,
) -> list[dict]:
    """
    解析 BI 考勤 Excel 文件。

    :param file_path: Excel 文件路径
    :param bi_month: BI 考勤月份，如 "202608"
    :param filter_project: 过滤项目名，只返回该项目的记录（用于按登录用户项目过滤）
    :return: 解析后的考勤记录列表
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if len(rows) < 2:
        wb.close()
        return []

    header = [str(c) if c is not None else "" for c in rows[0]]

    org_keywords = ("组织", "项目")
    org_idx = next((i for i, h in enumerate(header) if h in org_keywords), 0)
    id_idx = next((i for i, h in enumerate(header) if h == "工号"), 1)
    name_idx = next((i for i, h in enumerate(header) if h == "姓名"), 2)
    pos_keywords = ("岗位", "部门")
    pos_idx = next((i for i, h in enumerate(header) if h in pos_keywords), 3)

    day_cols = []
    day_labels = []
    for i, h in enumerate(header):
        m = re.match(r"^(\d+)(?:日)?$", h)
        if m:
            day_cols.append(i)
            day_labels.append(f"{m.group(1)}日")

    results = []
    for row in rows[1:]:
        if not row or not any(row):
            continue

        org_path = str(row[org_idx]) if len(row) > org_idx and row[org_idx] else ""
        employee_id = str(row[id_idx]) if len(row) > id_idx and row[id_idx] else ""
        employee_name = str(row[name_idx]).strip() if len(row) > name_idx and row[name_idx] else ""
        position = str(row[pos_idx]) if len(row) > pos_idx and row[pos_idx] else ""

        # 使用映射表解析项目名
        project = resolve_project_from_bi_path(org_path) or org_path

        # 如果指定了过滤项目，只保留匹配的记录
        if filter_project and project != filter_project:
            continue

        attendance = {}
        for ci, col_idx in enumerate(day_cols):
            if col_idx >= len(row):
                continue
            cell_val = str(row[col_idx]) if row[col_idx] is not None else ""
            clock_times = [t.strip() for t in cell_val.split("\n") if t.strip()] if cell_val else []
            attendance[day_labels[ci]] = clock_times

        if not employee_name:
            continue

        results.append({
            "employee_name": employee_name,
            "employee_id": employee_id,
            "project_name": project,
            "position": position,
            "attendance": attendance,
        })

    wb.close()
    return results
