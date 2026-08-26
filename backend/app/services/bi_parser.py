"""
BI考勤数据解析模块。

核心功能：
1. 从BI路径解析标准项目名、业态、服务类型
2. 解析每日打卡时间（多个时间用换行分隔）
3. 计算上下班时间和工时
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, time, timedelta
from pathlib import Path

from app.core.config import settings

# 分公司名 -> 项目名映射
BRANCH_TO_PROJECT = {
    "南京金鹰国际物业集团有限公司马鞍山分公司": "马鞍山金鹰天地",
    "南京金鹰国际物业集团有限公司江宁分公司": "江宁金鹰天地",
    "扬州金鹰国际物业管理有限公司": "扬州文昌金鹰国际",
}

# 项目名别名（BI路径中的简称 -> 标准项目名）
PROJECT_ALIASES = {
    "金鹰中心": "南京金鹰中心",
    "汉中新城": "南京汉中新城",
    "珠江壹号": "南京珠江壹号",
    "湖滨天地": "南京湖滨天地",
    "金鹰世界": "南京金鹰世界",
}


def _get_db_path() -> str:
    return str(settings.storage_dir / "audit_platform.db")


def load_standard_projects() -> list[str]:
    """加载项目主档中的所有项目名。"""
    conn = sqlite3.connect(_get_db_path())
    rows = conn.execute(
        "SELECT DISTINCT project_name FROM project_business_types WHERE status='启用' ORDER BY project_name"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def extract_project_from_bi_path(bi_path: str, standard_projects: list[str] | None = None) -> str | None:
    """
    从BI路径中提取标准项目名。

    策略：
    1. 先检查是否是分公司路径
    2. 检查标准项目名是否直接出现在路径中
    3. 检查别名是否出现在路径中
    4. 从路径中提取项目关键词
    """
    if not bi_path:
        return None

    if standard_projects is None:
        standard_projects = load_standard_projects()

    # 1. 分公司路径特殊处理
    for branch, project in BRANCH_TO_PROJECT.items():
        if branch in bi_path:
            return project

    # 2. 标准项目名直接匹配（优先最长匹配）
    matched = []
    for proj in standard_projects:
        if proj in bi_path:
            matched.append(proj)
    if matched:
        return max(matched, key=len)

    # 3. 别名匹配
    for alias, full in PROJECT_ALIASES.items():
        if alias in bi_path:
            return full

    # 4. 从路径中提取项目关键词
    path = re.sub(r"^金鹰/物业集团/外包/", "", bi_path)
    path = re.sub(r"^金鹰/物业集团/南京金鹰国际物业集团有限公司[^/]+/", "", path)
    path = re.sub(r"^金鹰/金鹰商贸集团/连锁店/[^/]+/", "", path)
    parts = path.split("/")
    if parts:
        candidate = parts[0]
        for proj in standard_projects:
            if candidate in proj or proj in candidate:
                return proj
        return candidate

    return None


def infer_business_type_from_mapping(bi_path: str, project_name: str, service_type: str) -> str | None:
    """从映射表推断业态，支持双向前缀匹配。"""
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row

    # 策略1: 精确匹配或BI路径以映射路径开头
    rows = conn.execute(
        """
        SELECT business_type, bi_path FROM project_bi_mappings
        WHERE project_name=? AND service_type=? AND (bi_path=? OR ? LIKE bi_path || '/%')
        LIMIT 1
        """,
        (project_name, service_type, bi_path, bi_path),
    ).fetchall()
    if rows:
        conn.close()
        return rows[0]["business_type"]

    # 策略2: 映射路径以BI路径开头（BI路径是映射路径的前缀）
    rows = conn.execute(
        """
        SELECT business_type, bi_path FROM project_bi_mappings
        WHERE project_name=? AND service_type=? AND (? LIKE bi_path || '/%' OR bi_path LIKE ? || '/%')
        ORDER BY LENGTH(bi_path) DESC
        LIMIT 1
        """,
        (project_name, service_type, bi_path, bi_path),
    ).fetchall()
    if rows:
        conn.close()
        return rows[0]["business_type"]

    # 策略3: 尝试路径关键词推断（排除"物业集团"中的"物业"误匹配）
    # 先提取路径最后一段，避免在路径前缀中匹配关键词
    path_suffix = bi_path.split("/")[-1] if "/" in bi_path else bi_path
    keywords = {
        "商业": ["商场", "商业", "内场"],
        "住宅": ["住宅", "华府", "花园", "秋枫苑"],
        "酒店": ["酒店"],
        "写字楼": ["写字楼"],
        "街区": ["街区"],
    }
    for bt, kw_list in keywords.items():
        for kw in kw_list:
            if kw in path_suffix or kw in bi_path.split("/")[-2] if len(bi_path.split("/")) > 1 else False:
                conn.close()
                return bt

    conn.close()
    return None


def resolve_bi_path(bi_path: str, department: str) -> dict:
    """
    解析BI路径，返回标准项目名、业态、服务类型。
    """
    standard_projects = load_standard_projects()
    project_name = extract_project_from_bi_path(bi_path, standard_projects)

    dept_str = str(department).strip()
    if "保安" in dept_str:
        service_type = "保安"
    elif "保洁" in dept_str:
        service_type = "保洁"
    else:
        service_type = dept_str

    business_type = None
    if project_name:
        business_type = infer_business_type_from_mapping(bi_path, project_name, service_type)

    return {
        "bi_path": bi_path,
        "project_name": project_name,
        "business_type": business_type or "未确定",
        "service_type": service_type,
    }


def parse_clock_times(cell_value) -> list[str]:
    """
    解析单元格中的打卡时间。
    多个时间用换行符分隔，返回时间字符串列表。
    """
    if cell_value in ("", None):
        return []
    text = str(cell_value).strip()
    if not text:
        return []
    # 按换行符分割
    parts = re.split(r"[\r\n]+", text)
    times = [p.strip() for p in parts if p.strip()]
    return times


def parse_time(time_str: str) -> time | None:
    """把时间字符串解析为 time 对象。支持 H:MM 和 HH:MM 格式。"""
    time_str = str(time_str).strip()
    for fmt in ("%H:%M", "%H:%M:%S", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(time_str, fmt).time()
        except ValueError:
            continue
    # 尝试灵活匹配
    match = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        if 0 <= h < 24 and 0 <= m < 60:
            return time(h, m)
    return None


def calc_work_hours(clock_in: time, clock_out: time) -> float:
    """计算工时（小时）。处理跨天情况（如 20:00 -> 次日 8:00）。"""
    dt_in = datetime.combine(datetime.today(), clock_in)
    dt_out = datetime.combine(datetime.today(), clock_out)
    if dt_out < dt_in:
        dt_out += timedelta(days=1)
    delta = dt_out - dt_in
    return round(delta.total_seconds() / 3600, 2)


def parse_daily_clock(cell_value) -> dict:
    """
    解析每日打卡单元格，返回上下班时间和工时。

    返回：
    {
        "clock_times": ["6:21", "9:20", "17:23"],
        "clock_in": "6:21",
        "clock_out": "17:23",
        "work_hours": 11.03,
        "has_clock": True,
    }
    """
    times = parse_clock_times(cell_value)
    if not times:
        return {
            "clock_times": [],
            "clock_in": None,
            "clock_out": None,
            "work_hours": 0.0,
            "has_clock": False,
        }

    clock_in_str = times[0]
    clock_out_str = times[-1]

    clock_in = parse_time(clock_in_str)
    clock_out = parse_time(clock_out_str)

    work_hours = 0.0
    if clock_in and clock_out:
        work_hours = calc_work_hours(clock_in, clock_out)

    return {
        "clock_times": times,
        "clock_in": clock_in_str if clock_in else None,
        "clock_out": clock_out_str if clock_out else None,
        "work_hours": work_hours,
        "has_clock": True,
    }
