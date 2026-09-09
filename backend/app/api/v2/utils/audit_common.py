"""审核公共工具。

集中存放所有审核链路共用的「纯函数」：
- 姓名 / 岗位 / 业态 归一化
- 时间解析、跨天班次处理、跨天打卡拆分
- 排班单元格三态识别（休息 / 缺岗 / 人名）

新的「岗位履约审核」(app/service/audit_slot_service.py) 与旧审核引擎
(app/utils/rule_engine.py) 共用本模块，避免同一套逻辑在多处重复实现。
"""
from __future__ import annotations

import re
from datetime import datetime, date, time, timedelta
from typing import Any

from app.api.v2.models.schedule_models import Shift


# --------------------------------------------------------------------------
# 姓名归一化
# --------------------------------------------------------------------------
def normalize_employee_name(value: Any) -> str:
    """归一化员工姓名：去序号、去字母前缀、繁体转简体。"""
    text = str(value or "").strip()
    text = re.sub(r"^\d+", "", text)
    text = re.sub(r"^[A-Za-z]+", "", text)
    text = text.translate(str.maketrans({
        "俠": "侠", "俥": "车", "麗": "丽", "鳳": "凤", "蘭": "兰",
        "劉": "刘", "張": "张", "陳": "陈", "趙": "赵", "黃": "黄",
        "峰": "丰", "颖": "影",
    }))
    return text.strip()


def _levenshtein_distance(s1: str, s2: str) -> int:
    """计算两个字符串的编辑距离。"""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(
                prev[j + 1] + 1,
                curr[j] + 1,
                prev[j] + (0 if c1 == c2 else 1),
            ))
        prev = curr
    return prev[-1]


def fuzzy_match_name(target: str, candidates: set[str]) -> str | None:
    """模糊匹配名字：当完全匹配失败时，返回编辑距离为 1 的候选名。"""
    for name in candidates:
        if len(name) != len(target):
            continue
        if _levenshtein_distance(target, name) == 1:
            return name
    return None


# --------------------------------------------------------------------------
# 岗位 / 业态归一化
# --------------------------------------------------------------------------
def normalize_position_name(name: str) -> str:
    """归一化岗位名：去掉换行符、时长后缀（如 '7h'、'8h'）、去空格。

    '楼栋保洁\n7h' → '楼栋保洁'；'住宅保洁\n楼内岗8h' → '住宅保洁楼内岗'
    """
    text = str(name or "").replace("\n", "").replace("\r", "")
    return re.sub(r"\d+\.?\d*\s*h?", "", text).strip()


def normalize_business_type(value: str) -> str:
    """业态一一对应，不做归一化映射，原样返回。"""
    return str(value or "").strip()


# --------------------------------------------------------------------------
# 日期 / 时间工具
# --------------------------------------------------------------------------
def normalize_date(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%m/%d/%Y"]:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text[:10]


def parse_time_value(value: Any) -> time | None:
    if not value:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time().replace(second=0, microsecond=0)
    text = str(value).strip()
    if " " in text:
        text = text.split(" ")[-1]
    for fmt in ["%H:%M:%S", "%H:%M"]:
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            pass
    return None


def time_to_minutes(value: time | None) -> int | None:
    if value is None:
        return None
    return value.hour * 60 + value.minute


def get_next_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return date_str


def is_cross_midnight_shift(shift: Shift) -> bool:
    """判断班次是否跨天（夜班）：结束时间 <= 开始时间。"""
    start = parse_time_value(shift.start_time or "08:00")
    end = parse_time_value(shift.end_time or "17:00")
    if not start or not end:
        return False
    start_min = time_to_minutes(start)
    end_min = time_to_minutes(end)
    if start_min is None or end_min is None:
        return False
    return end_min <= start_min


def shift_clock_minutes(clock_times: list[str], shift: Shift) -> list[int]:
    """将打卡时间转为分钟数，处理跨天班次（次日凌晨打卡 +1440）。"""
    start = parse_time_value(shift.start_time or "08:00")
    end = parse_time_value(shift.end_time or "17:00")
    if not start:
        return []
    start_min = time_to_minutes(start)
    if start_min is None:
        return []
    end_min = time_to_minutes(end) if end else start_min + 480
    if end_min is None:
        end_min = start_min + 480
    cross_midnight = end_min <= start_min
    result = []
    for t in clock_times:
        p = parse_time_value(t)
        if not p:
            continue
        m = time_to_minutes(p)
        if m is None:
            continue
        if cross_midnight and m < start_min and m <= end_min + 120:
            m += 1440
        result.append(m)
    return sorted(result)


# --------------------------------------------------------------------------
# 跨天打卡拆分
# --------------------------------------------------------------------------
def split_cross_day_clocks(
    clock_times: list[str],
    prev_shift: Shift | None,
) -> tuple[list[str], list[str]]:
    """把某天的打卡拆成「属于当天」与「属于前一天跨天班次的下班卡」两组。

    夜班 22:00 上班、次日 06:00 下班时，06:00 这张卡会记在第二天头上，
    但它证明的是「前一天有人上班」，不能拿来当作「第二天这个岗位有人」。
    不做这一步，凌晨的下班卡会让大量实际没人的岗位被误判为有人到岗。
    """
    if not clock_times:
        return [], []
    if prev_shift is None or not is_cross_midnight_shift(prev_shift):
        return list(clock_times), []
    end_min = time_to_minutes(parse_time_value(prev_shift.end_time))
    if end_min is None:
        return list(clock_times), []
    today_clocks = []
    prev_day_clocks = []
    for text in clock_times:
        minutes = time_to_minutes(parse_time_value(text))
        # 早于前一班次下班时刻的卡，归属前一天那个跨天班次
        if minutes is not None and minutes > end_min:
            today_clocks.append(text)
        else:
            prev_day_clocks.append(text)
    return today_clocks, prev_day_clocks


# --------------------------------------------------------------------------
# 从排班原始岗位名里解析班次
# --------------------------------------------------------------------------
SHIFT_TIME_RE = re.compile(r"(\d{1,2}[:：]\d{2})\s*[-~—至到]\s*(\d{1,2}[:：]\d{2})")


def parse_shift_time_text(value: Any) -> tuple[str, str]:
    text = str(value or "").replace("：", ":").strip()
    match = SHIFT_TIME_RE.search(text)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def shift_from_raw_position(raw: str) -> Shift | None:
    """从排班槽位的 raw_position（含时间段后缀）里解析出班次。

    如 'PA1（5:00-12:00）' → Shift(start='5:00', end='12:00')。
    无时间段信息时返回 None，跨天处理退化为「不拆分」。
    """
    start, end = parse_shift_time_text(raw)
    if not start or not end:
        return None
    return Shift(shift_name=str(raw or ""), start_time=start, end_time=end)


# --------------------------------------------------------------------------
# 周几班次解析（支持"周一至周四7:00-21:30;周五至周日7:00-22:00"格式）
# --------------------------------------------------------------------------
WEEKDAY_MAP = {
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4,
    "六": 5, "日": 6, "天": 6,
}

WEEKDAY_SHIFT_RE = re.compile(
    r"(?:周|星期)([一二三四五六日天])"
    r"(?:至|到|-|~|—)(?:周|星期)?([一二三四五六日天])?"
)


def _parse_weekday_char(ch: str) -> int | None:
    """从单个汉字提取周几数字（0=周一, 6=周日）。"""
    return WEEKDAY_MAP.get(ch)


def _expand_weekday_range(start_wd: int, end_wd: int) -> list[int]:
    """展开周几范围，支持跨周边界（如 周六→周一 = [5,6,0]）。"""
    if start_wd == end_wd:
        return [start_wd]
    if start_wd < end_wd:
        return list(range(start_wd, end_wd + 1))
    return list(range(start_wd, 7)) + list(range(0, end_wd + 1))


def parse_shift_by_weekday(value: Any) -> list[tuple[list[int], str, str]]:
    """解析含周几信息的班次文本，返回 [(weekdays, start_time, end_time), ...]。

    weekdays 为 0=周一 ~ 6=周日 的列表。无周几前缀的时段默认适用于全周。

    示例:
      "周一至周四7:00-21:30;周五至周日7:00-22:00"
        → [([0,1,2,3], "7:00", "21:30"), ([4,5,6], "7:00", "22:00")]
      "7:00-22:00"
        → [([0,1,2,3,4,5,6], "7:00", "22:00")]
      "领班13.5h周一至周四7:00-21:30;周五至周日7:00-22:00"
        → [([0,1,2,3], "7:00", "21:30"), ([4,5,6], "7:00", "22:00")]
    """
    text = str(value or "").replace("：", ":").strip()
    if not text:
        return []

    segments = re.split(r"[;；]", text)
    result: list[tuple[list[int], str, str]] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        time_match = SHIFT_TIME_RE.search(seg)
        if not time_match:
            continue
        start_time = time_match.group(1)
        end_time = time_match.group(2)

        weekday_match = WEEKDAY_SHIFT_RE.search(seg)
        if weekday_match:
            start_wd = _parse_weekday_char(weekday_match.group(1))
            end_char = weekday_match.group(2)
            if end_char:
                end_wd = _parse_weekday_char(end_char)
            else:
                end_wd = start_wd
            if start_wd is not None and end_wd is not None:
                weekdays = _expand_weekday_range(start_wd, end_wd)
            else:
                weekdays = list(range(7))
        else:
            weekdays = list(range(7))
        result.append((weekdays, start_time, end_time))

    return result


def get_shift_for_date(
    shifts: list[tuple[list[int], str, str]],
    date_str: str,
) -> tuple[str, str]:
    """根据日期返回当天对应的班次时间 (start_time, end_time)。

    Args:
        shifts: parse_shift_by_weekday 的返回值
        date_str: ISO 日期字符串，如 "2026-08-15"

    Returns:
        (start_time, end_time)，无匹配时返回 ("", "")
    """
    if not shifts:
        return "", ""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        wd = d.weekday()
    except (ValueError, TypeError):
        return "", ""
    for weekdays, start, end in shifts:
        if wd in weekdays:
            return start, end
    return "", ""


def strip_position_time_suffix(text: Any) -> str:
    """剥离岗位名里的时间段后缀，得到可用于聚合的岗位名。

    支持格式：
    - "B1卖场（周一至周四7:30-21:30）" → "B1卖场"
    - "领班13.5h周一至周四7:00-21:30;周五至周日7:00-22:00" → "领班"
    - "垃圾房6:00-14:15" → "垃圾房"
    - "酒店保洁7:00-22:00" → "酒店保洁"
    """
    raw = str(text or "").strip()
    if not raw:
        return raw

    # 1. 先去掉括号内的时间块（兼容中英文括号）
    stripped = re.sub(r"[（(][^（()）]*[)）]", "", raw)

    # 2. 去掉分号及之后的内容（多时段用分号分隔）
    stripped = re.sub(r";.*", "", stripped)

    # 3. 去掉 "Xh" / "X.Xh" 时长前缀（如 "13.5h"、"8h"）
    stripped = re.sub(r"\d+\.?\d*h", "", stripped)

    # 4. 去掉中文星期 + 时间范围模式（如 "周一至周四7:00-21:30"、"周五至周日7:00-22:00"）
    stripped = re.sub(r"[周|星期]\S*?(\d{1,2}[:：]\d{2})\s*[-~—至到]\s*\d{1,2}[:：]\d{2}", "", stripped)

    # 5. 去掉剩余的纯时间范围（如 "7:00-22:00"、"6:00-14:15"）
    stripped = re.sub(r"\d{1,2}[:：]\d{2}\s*[-~—至到]\s*\d{1,2}[:：]\d{2}", "", stripped)

    # 6. 清理空白
    stripped = re.sub(r"\s+", "", stripped)

    return stripped or raw


def parse_mid_clock_time(mid_clock_time: str) -> list[tuple[str, str, int]]:
    """解析中间卡时间字段，返回 [(开始时间, 结束时间, 打卡次数), ...]。

    规则：
    - 带括号 (12:00-13:00) 或 （12:00,13:00） → 该时间段内打 1 次卡
    - 不带括号 12:00-13:00 或 12:00,13:00 → 该时间段内打 2 次卡

    支持的分隔符：- ~ — 至 到 , ，
    支持全角冒号 ：

    Args:
        mid_clock_time: 如 "(12:00-13:00)" 或 "（12:00,13:00）" 或 "12:00-13:00"

    Returns:
        [(start_time, end_time, clock_count), ...]
    """
    if not mid_clock_time or not str(mid_clock_time).strip():
        return []

    text = str(mid_clock_time).replace("：", ":")
    result = []
    # 按分号拆分多个时间段（兼容中英文分号）
    segments = re.split(r"[;；]", text)
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue

        # 支持英文括号和中文括号
        is_bracketed = (
            (seg.startswith("(") and ")" in seg) or
            (seg.startswith("（") and "）" in seg)
        )
        # 提取时间范围（分隔符：- ~ — 至 到 , ，）
        match = re.search(
            r"(\d{1,2}:\d{2})\s*[-~—至到,，]\s*(\d{1,2}:\d{2})",
            seg,
        )
        if match:
            start_time = match.group(1)
            end_time = match.group(2)
            clock_count = 1 if is_bracketed else 2
            result.append((start_time, end_time, clock_count))

    return result


# --------------------------------------------------------------------------
# 排班单元格三态识别
# --------------------------------------------------------------------------
# 休息/未排班标记（空格或这些字样 = 当天该岗无人，不计审核）
REST_MARKERS = {"", "休息", "休", "调休", "无", "-", "/", "—", "×", "x", "0", "0.0", " "}
# 请假类（有正当原因缺勤，不计入缺岗、也不扣款，按忽略处理）
LEAVE_MARKERS = {"请假", "病假", "事假", "年假", "婚假", "丧假", "产假", "陪产假", "工伤", "年休"}
# 缺岗标记（显式写明 = 确定缺岗，直接计入扣款侧）
SHORTAGE_MARKERS = {"缺岗", "旷工", "未到岗", "空岗", "缺编", "未到", "无故缺岗", "脱岗"}


def split_employee_cell(value: Any) -> list[str]:
    """把排班单元格拆成人员姓名列表。"""
    if value in (None, "", 0, "0"):
        return []
    text = str(value).strip()
    if not text or text in REST_MARKERS:
        return []
    for sep in ["\n", "、", "，", ",", ";", "；"]:
        text = text.replace(sep, " ")
    return [
        part.strip()
        for part in text.split()
        if part.strip() and part.strip() not in {"休息", "休", "0"}
    ]


def classify_schedule_cell(raw: Any) -> dict:
    """把排班表的一个单元格识别为四种语义之一。

    返回 {"kind": "rest"|"leave"|"shortage"|"person", "names": [..], "raw": str}
    - rest    : 空 / 休息 / 未排班  → 当天该岗无人，不计入审核
    - leave   : 请假类            → 有正当原因，不计入缺岗、不扣款
    - shortage: 缺岗/旷工 等显式标记 → 确定缺岗，计入扣款侧
    - person  : 人名              → 用排班姓名作探针，去 BI 反查当天是否打卡
    """
    text = "" if raw is None else str(raw).strip()
    if text == "" or text in REST_MARKERS:
        return {"kind": "rest", "names": [], "raw": text}
    if text in LEAVE_MARKERS:
        return {"kind": "leave", "names": [], "raw": text}
    if text in SHORTAGE_MARKERS:
        return {"kind": "shortage", "names": [], "raw": text}
    names = split_employee_cell(text)
    if names:
        return {"kind": "person", "names": names, "raw": text}
    # 兜底：既非已知标记也非空，按休息忽略（避免脏数据污染审核）
    return {"kind": "rest", "names": [], "raw": text}
