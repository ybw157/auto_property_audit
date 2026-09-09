from pathlib import Path
from urllib.parse import quote
from fastapi.responses import FileResponse
from openpyxl import Workbook
from app.api.v2.core.config import settings


def _disposition(filename: str) -> dict:
    """构造 Content-Disposition 头，同时提供 ASCII fallback 和 UTF-8 编码名。"""
    ascii_name = filename.encode("ascii", "replace").decode("ascii")
    utf8_name = quote(filename)
    return {
        "Content-Disposition": (
            f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}'
        ),
    }


def generate_project_template():
    path = Path(settings.template_dir) / "项目基础资料模板.xlsx"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "项目基础信息"
        rows = [["项目名称", ""], ["项目编码", ""], ["业态", ""], ["供应商", ""], ["合同编号", ""], ["审核月份", ""], ["负责人", ""], ["模板版本", "v1.0"], ["备注", ""]]
        for row in rows:
            ws.append(row)
        ws = wb.create_sheet("合同编制表")
        ws.append(["岗位", "区域", "合同人数", "编制人员", "工时单价", "服务类型"])
        ws = wb.create_sheet("月度排班表")
        ws.append(["日期", "岗位", "区域", "姓名", "班次", "排班类型", "原岗位", "原人员", "备注"])
        ws = wb.create_sheet("班次标准")
        ws.append(["班次名称", "上班时间", "下班时间", "工时", "要求打卡次数", "允许打卡窗口"])
        wb.save(path)
    return FileResponse(path, headers=_disposition("项目基础资料模板.xlsx"))


def generate_attendance_template():
    path = Path(settings.template_dir) / "BI考勤模板.xlsx"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()
        ws = wb.active
        ws.title = "BI考勤"
        ws.append(["日期", "姓名", "打卡时间"])
        wb.save(path)
    return FileResponse(path, headers=_disposition("BI考勤模板.xlsx"))
