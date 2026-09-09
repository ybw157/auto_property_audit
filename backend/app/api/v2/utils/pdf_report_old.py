from pathlib import Path
import re
from xml.sax.saxutils import escape
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# 旧版从 app.core.config 引入 settings 并在 generate_pdf_report 里使用
# 本文件作为新代码的旧版报告生成库被复用：调用方直接传 report_dir，不再依赖 settings；
# 因此这里移除 settings 导入，generate_pdf_report 也不再导出。

def register_font():
    candidates = [
        # Linux (Docker) - Noto CJK and WenQuanYi
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
        # Windows
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                pdfmetrics.registerFont(TTFont("CNFont", path))
                return "CNFont"
            except Exception:
                continue
    return "Helvetica"

FONT_NAME = register_font()

# 旧版的 generate_pdf_report 依赖 settings.report_dir，本文件作为旧版报告生成库被复用：
# 调用方（utils/pdf_report.py 适配层）直接传 report_dir，所以这里不再导出该函数。

def styles():
    base = getSampleStyleSheet()
    base.add(ParagraphStyle(name="CNTitle", fontName=FONT_NAME, fontSize=18, leading=26, spaceAfter=12))
    base.add(ParagraphStyle(name="CNHeading", fontName=FONT_NAME, fontSize=13, leading=20, spaceBefore=8, spaceAfter=6, textColor=colors.HexColor("#1E3A8A")))
    base.add(ParagraphStyle(name="CNBody", fontName=FONT_NAME, fontSize=10, leading=16))
    base.add(ParagraphStyle(name="CNNote", fontName=FONT_NAME, fontSize=9, leading=14, textColor=colors.HexColor("#475569")))
    return base

# def infer_service_type(results: dict) -> str:
#     """从审核结果中推断服务类型（保安/保洁/保安保洁）。"""
#     contracts = results.get("contracts", [])
#     service_types = set()
#     for c in contracts:
#         st = str(c.get("service_type", "")).strip()
#         if st:
#             service_types.add(st)
#     if not service_types:
#         # 从排班岗位名推断
#         for detail in results.get("attendance_details", [])[:200]:
#             pos = str(detail.get("position", ""))
#             if "保安" in pos:
#                 service_types.add("保安")
#             elif "保洁" in pos:
#                 service_types.add("保洁")
#         if not service_types:
#             return "保洁"
#     if "保安" in service_types and "保洁" in service_types:
#         return "保安保洁"
#     if "保安" in service_types:
#         return "保安"
#     return "保洁"

def build_pdf(batch_id: int, report_dir: Path, title: str, results: dict, keys: list[str]) -> dict:
    file_path = report_dir / f"{title}.pdf"
    doc = SimpleDocTemplate(str(file_path), pagesize=landscape(A4), leftMargin=12*mm, rightMargin=12*mm, topMargin=12*mm, bottomMargin=12*mm)
    s = styles()
    story = [Paragraph(title, s["CNTitle"])]
    story.append(Paragraph(f"项目：{results.get('project_info', {}).get('项目名称', '')}　审核月份：{results.get('project_info', {}).get('审核月份', '')}", s["CNBody"]))
    story.append(Spacer(1, 8))
    for key in keys:
        rows = results.get(key, [])
        story.append(Paragraph(sheet_title(key), s["CNHeading"]))
        story.extend(table_flow(rows[:30], key))
        story.append(Spacer(1, 8))
    doc.build(story)
    return {"report_type": title, "file_format": "pdf", "file_path": str(file_path), "download_url": f"/files/reports/{batch_id}/{title}.pdf"}

def build_attendance_base_pdf(batch_id: int, report_dir: Path, results: dict) -> dict:
    # service_type = infer_service_type(results)
    title = f"考勤明细"
    file_path = report_dir / f"{title}.pdf"
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=landscape(A4),
        leftMargin=6*mm,
        rightMargin=6*mm,
        topMargin=8*mm,
        bottomMargin=8*mm,
    )
    s = styles()
    story = [
        Paragraph(title, s["CNTitle"]),
        Paragraph(
            f"项目：{results.get('project_info', {}).get('项目名称', '')}　"
            f"审核月份：{infer_report_month(results)}　"
            f"审核业态：{'、'.join(results.get('audit_business_types', [])) or '未识别'}",
            s["CNBody"],
        ),
        Spacer(1, 5),
        Paragraph("说明：本表以 BI 考勤宽表为底表，黄色背景为异常（缺勤/漏打卡/迟到/早退/工时不足等），红色文字为异常原因，黑色文字为正常。", s["CNBody"]),
        Spacer(1, 6),
    ]
    tables = build_attendance_base_tables(results)
    if not tables:
        story.append(Paragraph("暂无考勤明细数据", s["CNBody"]))
    for index, table in enumerate(tables):
        if index:
            story.append(PageBreak())
        story.append(table)
    doc.build(story)
    return {"report_type": title, "file_format": "pdf", "file_path": str(file_path), "download_url": f"/files/reports/{batch_id}/{title}.pdf"}



def infer_report_month(results: dict) -> str:
    explicit = results.get("project_info", {}).get("审核月份", "")
    if explicit:
        return explicit
    for row in results.get("attendance_details", []):
        value = str(row.get("work_date", ""))
        if len(value) >= 7:
            return value[:7]
    return ""

def build_attendance_base_tables(results: dict):
    details = results.get("attendance_details", [])
    if not details:
        return []
    grouped = {}
    position_time_map = {}
    for row in details:
        name = str(row.get("employee_name", ""))
        position = str(row.get("position", ""))
        area = str(row.get("area", ""))
        date_text = str(row.get("work_date", ""))
        shift = str(row.get("shift", ""))
        if not name or len(date_text) < 10:
            continue
        day = int(date_text[-2:])
        key = (name, position, area)
        grouped.setdefault(key, {})[day] = row
        if shift and not position_time_map.get(key):
            position_time_map[key] = shift
    max_day = max((max(by_day.keys()) for by_day in grouped.values()), default=30)
    max_day = min(max_day, 31)

    def build_half_page(day_start, day_end):
        num_days = day_end - day_start + 1
        row0 = ["岗位", "区域", "姓名"]
        row1 = ["", "", ""]
        for d in range(day_start, day_end + 1):
            row0.append(f"{d}日")
            row0.append("")
            row1.append("排班")
            row1.append("打卡")
        data = [row0, row1]
        row_styles = []
        cell_styles = []
        for key_index, ((name, position, area), by_day) in enumerate(sorted(grouped.items()), start=2):
            shift_info = position_time_map.get((name, position, area), position)
            data_row = [position, compact_area(area), name]
            for d in range(day_start, day_end + 1):
                item = by_day.get(d)
                schedule_cell, clock_cell = format_schedule_clock(item, shift_info)
                data_row.append(schedule_cell)
                data_row.append(clock_cell)
                if item and is_exception(item):
                    col_schedule = 3 + (d - day_start) * 2
                    col_clock = col_schedule + 1
                    # 异常单元格黄色背景，字体保持黑色（异常原因靠内联<font>标签变红）
                    row_styles.append(("BACKGROUND", (col_schedule, key_index), (col_clock, key_index), colors.HexColor("#FEF9C7")))
            data.append(data_row)

        col_w = [10*mm, 14*mm, 9*mm]
        for _ in range(num_days):
            col_w.append(8.15*mm)
            col_w.append(8.15*mm)
        wrapped = wrap_half_page_cells(data, is_header_row0=True)
        table = Table(wrapped, colWidths=col_w, repeatRows=2)
        base_style = [
            ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE", (0, 0), (-1, -1), 5.2),
            ("LEADING", (0, 0), (-1, -1), 6.5),
            ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#DBEAFE")),
            ("TEXTCOLOR", (0, 0), (-1, 1), colors.HexColor("#1E3A8A")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 2), (-1, -1), [colors.white, colors.white]),
            ("SPAN", (0, 0), (0, 1)),
            ("SPAN", (1, 0), (1, 1)),
            ("SPAN", (2, 0), (2, 1)),
            *row_styles,
            *cell_styles,
        ]
        for d_idx in range(num_days):
            col = 3 + d_idx * 2
            base_style.append(("SPAN", (col, 0), (col + 1, 0)))
        table.setStyle(TableStyle(base_style))
        return table

    tables = []
    tables.append(build_half_page(1, 15))
    if max_day >= 16:
        tables.append(build_half_page(16, max_day))
    return tables

def wrap_half_page_cells(data: list[list[str]], is_header_row0: bool = False):
    header_style = ParagraphStyle("HPHeader", fontName=FONT_NAME, fontSize=5.8, leading=7.0, alignment=1, textColor=colors.HexColor("#1E3A8A"), wordWrap="CJK")
    body_style = ParagraphStyle("HPBody", fontName=FONT_NAME, fontSize=5.0, leading=6.2, alignment=1, wordWrap="CJK")
    wrapped = []
    for row_index, row in enumerate(data):
        if row_index <= 1:
            wrapped.append([Paragraph(str(cell).replace("\n", "<br/>") if cell else "", header_style) for cell in row])
        else:
            cells = []
            for cell in row:
                text = str(cell)
                # 始终用黑色body_style，异常原因靠内联<font color>标签变红
                cells.append(Paragraph(text.replace("\n", "<br/>") if text else "", body_style))
            wrapped.append(cells)
    return wrapped

def format_schedule_clock(row: dict | None, shift_info: str = "") -> tuple[str, str]:
    if not row:
        return "", ""
    start_time = normalize_time_text(row.get("shift_start_time", ""))
    end_time = normalize_time_text(row.get("shift_end_time", ""))
    if start_time and end_time:
        raw_shift = f"{start_time}-{end_time}"
    else:
        raw_shift = str(row.get("shift_name", "") or row.get("shift", "") or shift_info)
    schedule_text = extract_work_time(raw_shift) or raw_shift
    clock_times = row.get("clock_times", "")
    if isinstance(clock_times, list):
        clock_text = "\n".join(str(t) for t in clock_times if t)
    else:
        clock_text = str(clock_times).replace(";", "\n").replace(" ", "\n")
    if is_exception(row):
        reason = str(row.get("exception_type") or row.get("exception_reason") or "异常")
        clock_text = f"{clock_text}\n<font color='#C41E3A'>{reason}</font>" if clock_text.strip() else f"<font color='#C41E3A'>{reason}</font>"
    return schedule_text, clock_text

def extract_work_time(value: str) -> str:
    text = str(value or "").replace("：", ":")
    match = re.search(r"(\d{1,2}:\d{2})\s*[-~—至到]\s*(\d{1,2}:\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    return ""

def normalize_time_text(value) -> str:
    text = str(value or "").replace("：", ":").strip()
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return ""
    return f"{int(match.group(1))}:{match.group(2)}"

def compact_area(value: str) -> str:
    text = str(value or "")
    replacements = {
        "住宅区域清洁与管理": "住宅区域",
        "住宅院内、停车场": "院内停车场",
        "江宁金鹰天地广场": "广场",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text

def wrap_table_cells(data: list[list[str]], font_size: float = 6, leading: float = 7):
    body_style = ParagraphStyle("TinyTableCell", fontName=FONT_NAME, fontSize=font_size, leading=leading, alignment=1, wordWrap="CJK")
    header_style = ParagraphStyle("TinyTableHeader", fontName=FONT_NAME, fontSize=font_size, leading=leading, alignment=1, textColor=colors.HexColor("#1E3A8A"), wordWrap="CJK")
    wrapped = []
    for row_index, row in enumerate(data):
        style = header_style if row_index == 0 else body_style
        wrapped.append([Paragraph(str(cell).replace("\n", "<br/>"), style) for cell in row])
    return wrapped

def format_attendance_cell(row: dict | None) -> str:
    if not row:
        return ""
    clock_times = row.get("clock_times", "")
    if isinstance(clock_times, list):
        text = "<br/>".join(str(item) for item in clock_times)
    else:
        text = str(clock_times).replace(";", "<br/>").replace(" ", "<br/>")
    if is_exception(row):
        reason = str(row.get("exception_type") or row.get("exception_reason") or "异常")
        text = f"{text}<br/><font color='#991B1B'>{reason}</font>" if text else f"<font color='#991B1B'>{reason}</font>"
    return text

def is_exception(row: dict) -> bool:
    status = str(row.get("status", ""))
    exception_type = str(row.get("exception_type", ""))
    reason = str(row.get("exception_reason", ""))
    normal_texts = ("正常", "无", "None", "无异常", "")
    return any(text and text not in normal_texts for text in [exception_type, reason]) or status not in normal_texts
def build_combined_report_pdf(batch_id: int, report_dir: Path, results: dict) -> dict:
    """生成合并报告PDF：AI审核汇总 + 扣款金额报告合并为一个PDF。"""
    # service_type = infer_service_type(results)
    title = f"AI审核汇总与扣款报告"
    file_path = report_dir / f"{title}.pdf"
    doc = SimpleDocTemplate(str(file_path), pagesize=landscape(A4), leftMargin=10*mm, rightMargin=10*mm, topMargin=12*mm, bottomMargin=12*mm)
    s = styles()
    project_info = results.get("project_info", {})
    summary = results.get("summary", {})
    audit_month = format_audit_month(project_info.get("审核月份") or infer_report_month(results))
    business_type = "、".join(results.get("audit_business_types", [])) or "未识别"
    schedule_count = summary.get("schedule_task_count", 0) or 0
    first_exception_count = summary.get("exception_count", 0) or 0
    first_exception_rate = summary.get("first_exception_rate") or (round(first_exception_count / schedule_count * 100, 1) if schedule_count > 0 else 0)
    confirmed_exception_count = summary.get("confirmed_exception_count", 0) or 0
    confirmed_exception_rate = summary.get("confirmed_exception_rate") or (round(confirmed_exception_count / schedule_count * 100, 1) if schedule_count > 0 else 0)
    total_deduction = summary.get("total_deduction", 0) or 0
    confirmed_count = summary.get("confirmed_count", 0) or 0
    skipped_count = summary.get("skipped_count", 0) or 0
    attendance_deduction = summary.get("attendance_deduction_amount", 0) or 0
    position_deduction = summary.get("position_deduction_amount", 0) or 0

    story = [
        Paragraph(f"外包考勤 AI 审核汇总与扣款报告", s["CNTitle"]),
        Paragraph(f"{project_info.get('项目名称', '')}（{business_type}）｜{audit_month}｜生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", s["CNBody"]),
        Spacer(1, 8),
        Paragraph("一、项目概况", s["CNHeading"]),
    ]
    story.extend(simple_table([
        ["项目名称", project_info.get("项目名称", ""), "业态", business_type, "审核月份", audit_month],
        ["合同编号", project_info.get("合同编号", ""), "供应商", project_info.get("供应商", ""), "启用合同", (results.get("active_contract") or {}).get("contract_name", "未匹配")],
    ], [24*mm, 42*mm, 20*mm, 28*mm, 24*mm, 42*mm]))

    # 核心审核指标
    story.append(Paragraph("二、核心审核指标", s["CNHeading"]))
    story.extend(simple_table([
        ["审核天数", summary.get("audited_days", 0), "岗位数", summary.get("position_count", 0), "排班任务", schedule_count],
        ["第一次异常数", first_exception_count, "第一次异常率", f"{first_exception_rate}%", "确认后异常数", confirmed_exception_count],
        ["确认后异常率", f"{confirmed_exception_rate}%", "确认异常条数", confirmed_count, "未确认条数", skipped_count],
        ["总扣款金额", f"{total_deduction}元", "考勤扣款", f"{attendance_deduction}元", "岗位扣款", f"{position_deduction}元"],
    ], [24*mm, 32*mm, 24*mm, 32*mm, 24*mm, 32*mm]))

    # 异常率说明
    story.append(Paragraph("三、异常率说明", s["CNHeading"]))
    story.append(Paragraph(f"第一次审核异常率 = 第一次异常数 / 排班任务 = {first_exception_count} / {schedule_count} = {first_exception_rate}%。该数值反映系统初次审核发现的异常比例。", s["CNBody"]))
    story.append(Paragraph(f"确认后异常率 = 确认异常条数 / 排班任务 = {confirmed_exception_count} / {schedule_count} = {confirmed_exception_rate}%。该数值反映项目确认后实际需扣款的异常比例。", s["CNBody"]))
    story.append(Paragraph(f"本次审核共确认{confirmed_count}条异常，未确认{skipped_count}条，总扣款{total_deduction}元。", s["CNBody"]))

    # 审核总结
    story.append(Paragraph("四、审核总结（可直接复制）", s["CNHeading"]))
    story.append(Paragraph(build_copyable_summary(results), s["CNBody"]))

    # 排班审核及扣款明细
    story.append(Paragraph("五、排班审核及扣款明细", s["CNHeading"]))
    story.extend(table_flow(build_position_summary_rows(results), "ai_position_summary"))

    # 扣款明细
    deductions = results.get("attendance_deductions", [])
    if deductions:
        story.append(Paragraph("六、扣款明细", s["CNHeading"]))
        story.extend(table_flow(deductions[:50], "attendance_deductions"))

    # 人员扣款汇总
    deduction_summary = results.get("deduction_summary", [])
    if deduction_summary:
        story.append(Paragraph("七、人员扣款汇总", s["CNHeading"]))
        # 判断数据格式：如果是按员工汇总格式（有employee_name），用table_flow；否则用simple_table展示总额
        first = deduction_summary[0] if deduction_summary else {}
        if "employee_name" in first:
            story.extend(table_flow(deduction_summary[:30], "deduction_summary"))
        else:
            # 总额格式：{position_deduction_amount, attendance_deduction_amount, total_deduction_amount}
            summary_data = [
                ["人员考勤扣款", f"{first.get('attendance_deduction_amount', 0)}元"],
                ["岗位扣款", f"{first.get('position_deduction_amount', 0)}元"],
                ["合计扣款", f"{first.get('total_deduction_amount', 0)}元"],
            ]
            story.extend(simple_table(summary_data, [40*mm, 30*mm]))
        # 如果有按员工汇总数据，也展示
        emp_summary = results.get("employee_deduction_summary", [])
        if emp_summary:
            story.append(Spacer(1, 6))
            story.append(Paragraph("按员工扣款汇总：", s["CNBody"]))
            story.extend(table_flow(emp_summary[:30], "deduction_summary"))

    # 管理建议
    story.append(Paragraph("八、管理建议", s["CNHeading"]))
    for line in build_management_suggestions(results):
        story.append(Paragraph(line, s["CNBody"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph("本报告由 AI 考勤审核系统自动生成，扣款金额按合同细则计算，请结合合同、排班表、BI原始考勤和现场管理记录复核确认。", s["CNNote"]))
    doc.build(story)
    return {"report_type": title, "file_format": "pdf", "file_path": str(file_path), "download_url": f"/files/reports/{batch_id}/{title}.pdf"}

def sheet_title(key: str) -> str:
    return {
        "attendance_details": "考勤明细",
        "position_fulfillment": "排班审核汇总",
        "deduction_summary": "扣款汇总",
    }.get(key, key)

COLUMN_LABELS = {
    "work_date": "日期",
    "position": "岗位",
    "area": "区域",
    "employee_name": "姓名",
    "shift_name": "班次",
    "clock_times": "打卡时间",
    "exception_type": "异常",
    "deduction_amount": "扣款(元)",
    "contract_headcount": "合同人数(不参与审核)",
    "scheduled_headcount": "排班人数",
    "actual_attendance_count": "实际出勤人数",
    "shortage_count": "缺编人数(停用)",
    "shortage_hours": "缺编工时(停用)",
    "hourly_rate": "工时单价",
    "position_deduction_amount": "岗位扣款(元)",
    "attendance_deduction_amount": "考勤扣款(元)",
    "total_deduction_amount": "合计扣款(元)",
    "position_deduction_calc": "审核依据",
    "position": "岗位",
    "scheduled_employee": "排班人员",
    "actual_employee": "实际出勤人",
    "attendance_days": "出勤",
    "late_count": "迟到",
    "early_leave_count": "早退",
    "absence_count": "缺勤",
    "missing_clock_count": "漏打卡",
    "status": "状态",
    "schedule_time": "排班班次",
    "date": "日期",
    "actual_person": "实际出勤人",
    "clock_records": "打卡记录",
    "exception_desc": "异常",
    "deduction_rule": "扣款项目",
    "calculation_detail": "计算说明",
    "employee_name": "姓名",
    "exception_count": "异常次数",
    "total_deduction": "总扣款(元)",
}

TABLE_COLUMNS = {
    "position_fulfillment": ["work_date", "position", "area", "scheduled_headcount", "actual_attendance_count", "result_status", "calculation_detail"],
    "deduction_summary": ["employee_name", "position", "exception_count", "total_deduction"],
    "ai_position_summary": ["position", "scheduled_employee", "actual_employee", "area", "schedule_time", "attendance_days", "late_count", "early_leave_count", "absence_count", "missing_clock_count", "position_deduction_calc", "deduction_amount", "status"],
    "ai_exception_detail": ["position", "scheduled_employee", "schedule_time", "date", "actual_person", "clock_records", "exception_desc", "deduction_amount"],
    "attendance_deductions": ["work_date", "employee_name", "position", "exception_type", "deduction_rule", "deduction_amount", "calculation_detail"],
}

def table_flow(rows: list[dict], table_key: str = ""):
    if not rows:
        return [Paragraph("暂无数据", styles()["CNBody"])]
    headers = [key for key in TABLE_COLUMNS.get(table_key, list(rows[0].keys())[:8]) if key in rows[0]]
    data = [[COLUMN_LABELS.get(header, header) for header in headers]]
    for row in rows:
        data.append([format_table_cell(row.get(h, ""), h, table_key) for h in headers])
    table = Table(wrap_table_data(data, table_key), colWidths=table_col_widths(headers, table_key), repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE9FE")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [table]

def format_table_cell(value, header: str, table_key: str) -> str:
    text = str(value or "")
    if header in {"scheduled_employee", "actual_employee"}:
        return text[:42]
    if header in {"position_deduction_calc", "exception_desc", "clock_records"}:
        return text[:80]
    if header in {"area", "schedule_time"}:
        return text[:36]
    return text[:28]

def wrap_table_data(data: list[list[str]], table_key: str):
    header_style = ParagraphStyle(f"{table_key}_Header", fontName=FONT_NAME, fontSize=9, leading=11, alignment=1, textColor=colors.HexColor("#1E3A8A"), wordWrap="CJK", splitLongWords=1)
    body_style = ParagraphStyle(f"{table_key}_Body", fontName=FONT_NAME, fontSize=9, leading=11, alignment=1, wordWrap="CJK", splitLongWords=1)
    wrapped = []
    for row_index, row in enumerate(data):
        style = header_style if row_index == 0 else body_style
        wrapped.append([Paragraph(escape(str(cell)).replace("\n", "<br/>"), style) for cell in row])
    return wrapped

def table_col_widths(headers: list[str], table_key: str):
    if table_key == "ai_position_summary":
        width_map = {
            "position": 22*mm,
            "scheduled_employee": 28*mm,
            "actual_employee": 28*mm,
            "area": 24*mm,
            "schedule_time": 24*mm,
            "attendance_days": 13*mm,
            "late_count": 11*mm,
            "early_leave_count": 11*mm,
            "absence_count": 11*mm,
            "missing_clock_count": 13*mm,
            "position_deduction_calc": 38*mm,
            "deduction_amount": 18*mm,
            "status": 14*mm,
        }
        return [width_map.get(header, 18*mm) for header in headers]
    if table_key == "ai_exception_detail":
        width_map = {
            "position": 28*mm,
            "scheduled_employee": 24*mm,
            "schedule_time": 24*mm,
            "date": 12*mm,
            "actual_person": 22*mm,
            "clock_records": 32*mm,
            "exception_desc": 50*mm,
            "deduction_amount": 18*mm,
        }
        return [width_map.get(header, 22*mm) for header in headers]
    if table_key == "position_fulfillment":
        width_map = {
            "work_date": 28*mm,
            "position": 36*mm,
            "area": 42*mm,
            "scheduled_headcount": 26*mm,
            "actual_attendance_count": 28*mm,
            "result_status": 28*mm,
            "calculation_detail": 78*mm,
        }
        widths = [width_map.get(header, 28*mm) for header in headers]
        return widths[:len(headers)]
    return None

def simple_table(data: list[list[object]], col_widths: list[float]):
    body_style = ParagraphStyle("SimpleCell", fontName=FONT_NAME, fontSize=9, leading=12, alignment=1, wordWrap="CJK")
    table = Table([[Paragraph(escape(str(cell)), body_style) for cell in row] for row in data], colWidths=col_widths)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [table, Spacer(1, 8)]

def format_audit_month(value: str) -> str:
    text = str(value or "")
    match = re.search(r"(\d{4})[-年/](\d{1,2})", text)
    if not match:
        return text
    year = int(match.group(1))
    month = int(match.group(2))
    days = month_days(year, month)
    return f"{year}年{month}月（{days}天）"

def month_days(year: int, month: int) -> int:
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    return (next_month - datetime(year, month, 1)).days

def build_copyable_summary(results: dict) -> str:
    project = results.get("project_info", {}).get("项目名称", "")
    business_type = "、".join(results.get("audit_business_types", [])) or "保洁"
    # service_type = infer_service_type(results)
    audit_month = format_audit_month(results.get("project_info", {}).get("审核月份") or infer_report_month(results))
    summary = results.get("summary", {})
    exception_stats = results.get("exception_statistics", [])
    top_exceptions = "、".join([f"{item.get('employee_name', '')}{item.get('exception_type', '')}{item.get('exception_count', item.get('count', 0))}次" for item in exception_stats[:3]]) or "无明显人员异常"
    attendance_deduction = summary.get("attendance_deduction_amount", 0) or 0
    total_deduction = summary.get("total_deduction", 0) or 0
    return (
        f"{project}{business_type}外包{audit_month}考勤审核完成。"
        f"本次以月度排班表为唯一审核依据，覆盖{summary.get('audited_days', 0)}个日期、{summary.get('position_count', 0)}类岗位、{summary.get('schedule_task_count', 0)}条排班任务，"
        f"人员考勤异常{summary.get('exception_count', 0)}人次。"
        f"重点异常为：{top_exceptions}。"
        f"人员考勤扣款{attendance_deduction}元，"
        f"建议扣款合计{total_deduction}元。"
    )

def build_position_summary_rows(results: dict) -> list[dict]:
    grouped = {}
    position_rows = results.get("position_fulfillment", [])
    details = results.get("attendance_details", [])
    for row in position_rows:
        key = (row.get("position", ""), row.get("area", ""))
        item = grouped.setdefault(key, {
            "position": row.get("position", ""),
            "scheduled_employee": set(),
            "actual_employee": set(),
            "area": row.get("area", ""),
            "schedule_time": "",
            "attendance_days": 0,
            "late_count": 0,
            "early_leave_count": 0,
            "absence_count": 0,
            "missing_clock_count": 0,
            "deduction_amount": 0,
        })
        item["attendance_days"] += float(row.get("actual_attendance_count", 0) or 0)
    for detail in details:
        key = (detail.get("position", ""), detail.get("area", ""))
        item = grouped.get(key)
        if not item:
            continue
        name = str(detail.get("employee_name", ""))
        if name:
            item["scheduled_employee"].add(name)
        if float(detail.get("actual_hours", 0) or 0) > 0 and name:
            item["actual_employee"].add(name)
        exception = str(detail.get("exception_type", ""))
        if "迟到" in exception:
            item["late_count"] += 1
        if "早退" in exception:
            item["early_leave_count"] += 1
        if "缺勤" in exception:
            item["absence_count"] += 1
        if "漏打卡" in exception:
            item["missing_clock_count"] += 1
        item["deduction_amount"] += float(detail.get("deduction_amount", 0) or 0)
        if not item["schedule_time"]:
            item["schedule_time"] = format_detail_schedule_time(detail)
    rows = []
    for item in grouped.values():
        rows.append({
            "position": item["position"],
            "scheduled_employee": "、".join(sorted(item["scheduled_employee"]))[:32],
            "actual_employee": "、".join(sorted(item["actual_employee"]))[:32],
            "area": item["area"],
            "schedule_time": item["schedule_time"],
            "attendance_days": int(item["attendance_days"]),
            "late_count": item["late_count"] if item["late_count"] is not None else 0,
            "early_leave_count": item["early_leave_count"] if item["early_leave_count"] is not None else 0,
            "absence_count": item["absence_count"] if item["absence_count"] is not None else 0,
            "missing_clock_count": item["missing_clock_count"] if item["missing_clock_count"] is not None else 0,
            "position_deduction_calc": "以月度排班表为依据，BI考勤仅验证本人打卡；不自动判定顶岗/调岗/换班。",
            "deduction_amount": round(item["deduction_amount"], 2),
            "status": "高风险" if item["deduction_amount"] > 0 or item["absence_count"] or item["late_count"] or item["early_leave_count"] or item["missing_clock_count"] else "正常",
        })
    return sorted(rows, key=lambda row: float(row.get("deduction_amount", 0) or 0), reverse=True)

def build_exception_detail_rows(results: dict) -> list[dict]:
    rows = []
    for item in results.get("attendance_deductions", [])[:80]:
        detail = find_attendance_detail(results, item)
        rows.append({
            "position": item.get("position", ""),
            "scheduled_employee": item.get("employee_name", ""),
            "schedule_time": format_detail_schedule_time(detail),
            "date": str(item.get("work_date", ""))[-2:] + "日" if item.get("work_date") else "",
            "actual_person": item.get("employee_name", ""),
            "clock_records": detail.get("clock_times", "") if detail else "",
            "exception_desc": item.get("rule_name") or item.get("exception_type", ""),
            "deduction_amount": item.get("deduction_amount", 0),
        })
    return rows

def find_attendance_detail(results: dict, deduction: dict) -> dict:
    for item in results.get("attendance_details", []):
        if item.get("employee_name") == deduction.get("employee_name") and item.get("work_date") == deduction.get("work_date") and item.get("position") == deduction.get("position"):
            return item
    return {}

def format_detail_schedule_time(detail: dict) -> str:
    if not detail:
        return ""
    start = detail.get("shift_start_time", "")
    end = detail.get("shift_end_time", "")
    return f"{start}-{end}" if start and end else str(detail.get("shift_name", ""))

def build_management_suggestions(results: dict) -> list[str]:
    deduction = (results.get("deduction_summary") or [{}])[0]
    exception_stats = results.get("exception_statistics", [])
    suggestions = [
        "1.【重要】所有异常均以月度排班表为唯一审核依据；如排班与BI实际出勤不一致，请项目核实并修改月度排班表后重新上传。",
        "2. 对迟到、早退、漏打卡、工时不足、缺勤等异常，应保留BI原始考勤截图或导出记录。",
    ]
    if exception_stats:
        top = exception_stats[0]
        suggestions.append(f"3. 本月异常最集中的人员为{top.get('employee_name', '')}，主要问题为{top.get('exception_type', '')}，建议供应商专项复盘。")
    suggestions.append(f"4. 本月建议扣款{deduction.get('total_deduction_amount', 0)}元，从当月服务费中扣除，并要求供应商签字确认。")
    suggestions.append("5. 系统不自动判断顶岗、调岗、调休或换班；最终确认结果以项目确认后的最新月度排班表为准。")
    return suggestions
