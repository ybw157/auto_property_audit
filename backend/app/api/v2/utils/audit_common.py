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
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from ..models.schedule_models import Shift


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

    }))
    text = re.sub(r"[（(].*?[)）]", "", text)
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


def resolve_cross_midnight(field_raw: str, start: str, end: str) -> bool:
    """跨夜班次判定：编制表字段优先，时间数值关系兜底。

    判定顺序：
    1. 编制表 cross_midnight 列明确标「是」→ 跨夜 True；
    2. 明确标「否」→ 跨夜 False（字段已明确判定，不再回退时间）；
    3. 其它（空白 / 未标注 / 其它值）→ 兜底按班次时间数值关系：
       开始时间数值 > 结束时间数值（大数在前、小数在后，统一 24 小时制）→ 跨夜。
       例如 19:00-07:00（1140 > 420）、22:00-06:00（1320 > 360）判为跨夜；
       07:00-19:00（420 < 1140）不跨夜。
    """
    raw = (field_raw or "").strip()
    if raw == "是":
        return True
    if raw == "否":
        return False
    # 兜底：无法通过字段明确判定时，用时间数值关系
    s = parse_time_value(start)
    e = parse_time_value(end)
    sm = time_to_minutes(s) if s else None
    em = time_to_minutes(e) if e else None
    if sm is None or em is None:
        return False
    return sm > em


# 月均天数常数（365 ÷ 12）。保安岗缺勤/缺岗日服务费权威口径的分母。
MONTH_AVG_DAYS = 30.42


def round_money(x) -> float:
    """金额四舍五入到小数点后两位（ROUND_HALF_UP；费用域均为非负数）。

    注意不能用内置 round()：它是银行家舍入（round(2.675, 2) 会偏），不是真四舍五入。
    全系统金额口径（2026-10-19 用户拍板）：费率/行金额保留两位小数，
    每天最终扣款先取两位小数再求和，保证行显示与合计恒等。
    """
    return float(Decimal(str(float(x or 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def daily_service_fee(hourly_rate, daily_hours, monthly_total, actual_count, service_type, monthly_rate=0) -> float:
    """缺勤/缺岗的日服务费（计费基数，缺编系数在此之上另乘）。

    保安岗（权威口径）：无工时单价概念，
        日费 = 岗位单价 ÷ 30.42
    - 岗位单价（monthly_rate）缺失/为 0 时兜底用月合价 ÷ 30.42（兼容旧编制表）；
      两者都无时再兜底：工时单价 × 日时长。

    保洁等其他服务类型保持原口径：工时单价 × 日时长。

    返回值为两位小数（四舍五入），保证行显示与合计口径一致。
    """
    hr = float(hourly_rate or 0)
    dh = float(daily_hours or 0)
    mt = float(monthly_total or 0)
    mr = float(monthly_rate or 0)
    if service_type == "保安":
        basis = mr if mr > 0 else mt
        if basis > 0:
            return round_money(basis / MONTH_AVG_DAYS)
    return round_money(hr * dh)


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
    is_cross: bool | None = None,
) -> tuple[list[str], list[str]]:
    """把某天的打卡拆成「属于当天」与「属于前一天跨天班次的下班卡」两组。

    夜班 22:00 上班、次日 06:00 下班时，06:00 这张卡会记在第二天头上，
    但它证明的是「前一天有人上班」，不能拿来当作「第二天这个岗位有人」。
    不做这一步，凌晨的下班卡会让大量实际没人的岗位被误判为有人到岗。

    is_cross：跨夜判定结果。优先使用调用方按「编制表字段+时间兜底」解析出的值；
    为 None 时回退到仅按时间关系（结束<=开始）判定，保持向后兼容。
    """
    if not clock_times:
        return [], []
    cross = (
        is_cross
        if is_cross is not None
        else (is_cross_midnight_shift(prev_shift) if prev_shift is not None else False)
    )
    if prev_shift is None or not cross:
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
# 解析「开始-结束」班次时间。兼容夜班「次日/第二天/次」跨天写法，
# 如 "20:00-次日8:00"、"19:00-第二天07:00"、"22:00-次6:00"。
# 「次日」等前缀放在非捕获组里，保证 group(1)/group(2) 仍是干净的 HH:MM，
# 下游 parse_shift_time_text / resolve_cross_midnight 无需改动即可正确判跨夜。
SHIFT_TIME_RE = re.compile(
    r"(?:次日|第二天|次)?\s*"
    r"(\d{1,2}[:：]\d{2})"
    r"\s*[-~—至到]\s*"
    r"(?:次日|第二天|次)?\s*"
    r"(\d{1,2}[:：]\d{2})"
)


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


def parse_position_shifts(position_name: Any, shift_time: Any) -> list[tuple[list[int], str, str]]:
    """解析岗位班次：岗位名称含时间段时优先按岗位名解析，否则回退 shift_time 字段。

    背景：编制表存在「一岗多班」写法——同一岗位按班次拆成多行（岗位名称列分别为
    「领班(07:45-15:00)」「领班(周一至周四15:00-21:15;周五至周日15:00-21:30)」），
    但班次时间列是合并单元格（如「7:45-15:00(周一至周四15:00-21:15）（周五-周日15:00-21:30）」）。
    直接解析 shift_time 会把第一段班次错配给所有拆分岗位（晚班被当成早班审核），
    且后半段星期范围（周五-周日）匹配不到任何班次而漏审。岗位名称列是按行独立的，
    内嵌的时间段才是该拆分岗位的真实班次。

    岗位名不含时间段（如「PA1」）时返回 shift_time 的解析结果，行为与原来一致。
    """
    name_shifts = parse_shift_by_weekday(position_name)
    if name_shifts:
        return name_shifts
    return parse_shift_by_weekday(shift_time)


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


# 隐含休息时长的合理区间（小时）。基线段跨度 − 日时长超出该区间时，
# 视为数据矛盾或基线选错，基线法放弃调整、回退岗位级日时长。
_WEEKDAY_HOURS_MIN_REST = 0.0
_WEEKDAY_HOURS_MAX_REST = 3.0


def weekday_adjusted_daily_hours(daily_hours: Any, shift_time: Any = None, *, shifts: list | None = None) -> dict[int, float] | None:
    """基线法：把岗位级日时长按星期段的班次跨度差，扩展成逐星期时长表。

    背景：合同计费口径的日时长是「净工时」（编制表日时长列，如 13h），
    而班次时刻跨度是「毛时长」（如 7:30-21:30 = 14h，含约 1h 休息）。
    当班次按星期分段且各段时长不同（周日至周四 13h / 周五周六 13.5h）时，
    缺岗扣款若统一按岗位级日时长计，周五六会被少扣。

    方法：净时长(某星期段) = daily_hours + (该段跨度 − 基线段跨度)。
    依据「各星期段休息时长相同」的弱假设，跨度差即净时长差。

    基线选择规则：
      1. 覆盖天数最多的星期段为基线（编制表日时长填的就是大多数日子的时长）；
      2. 隐含休息时长 = 基线跨度 − daily_hours 必须在 [0, 3] 小时内，
         越界视为数据矛盾，返回 None 由调用方回退；
      3. 天数平局时选跨度 >= daily_hours 且最接近的一段（隐含休息最短）。

    Args:
        daily_hours: 编制表日时长（净工时口径）。
        shift_time: 班次时间原文（shifts 未传时用它解析）。
        shifts: 已解析好的星期分段班次（parse_shift_by_weekday / parse_position_shifts
            的返回值），调用方已持有时传入以避免重复解析、并保持班次来源一致。

    Returns:
        {weekday(0=周一..6=周日): 当日净时长}；单段班次或数据不可靠时返回 None。
    """
    try:
        base = float(daily_hours or 0)
    except (TypeError, ValueError):
        return None
    if base <= 0:
        return None

    if shifts is None:
        shifts = parse_shift_by_weekday(shift_time)
    if len(shifts) < 2:
        return None

    spans: list[tuple[list[int], float]] = []
    for weekdays, start, end in shifts:
        s = time_to_minutes(parse_time_value(start))
        e = time_to_minutes(parse_time_value(end))
        if s is None or e is None:
            return None
        if e <= s:
            e += 24 * 60  # 跨夜班次
        spans.append((weekdays, (e - s) / 60.0))

    baseline = max(spans, key=lambda x: len(x[0]))
    top = [sp for sp in spans if len(sp[0]) == len(baseline[0])]
    if len(top) > 1:
        cands = [sp for sp in top if sp[1] >= base]
        baseline = min(cands, key=lambda x: x[1]) if cands else min(top, key=lambda x: x[1])
    baseline_span = baseline[1]

    rest = baseline_span - base
    if not (_WEEKDAY_HOURS_MIN_REST <= rest <= _WEEKDAY_HOURS_MAX_REST):
        return None

    result: dict[int, float] = {}
    for weekdays, span in spans:
        hours = base + (span - baseline_span)
        if hours <= 0:
            return None
        for wd in weekdays:
            result[wd] = round(hours, 4)
    return result if result else None


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


# 岗位名中的「班次/时段标签」：（白）（晚）（夜）（早）（中）/（白班）（晚班）...
# 也覆盖 (A)/(B)/(甲)/(乙) 等字母代号，以及中英文括号混用、空格差异等格式变体。
# 注意：strip_position_time_suffix 会把括号内容整体删掉，连（白）/（晚）一起删。
# 但白班与晚班是两个不同的编制岗位（人员、费率、排班都不同），聚合时必须保留标签，
# 否则同名多行岗位在白/晚槽位之间轮询分配时会串岗（晚班缺岗被记到白班头上）。
_POSITION_SHIFT_TAG_RE = re.compile(
    r"[（(]\s*"
    r"(白班|晚班|夜班|早班|中班|白|晚|夜|早|中"  # 中文班次名
    r"|A|B|C|D|甲|乙|丙|丁"                        # 字母/天干代号
    r"|白|夜|早)"                                   # 单字别名（冗余但显式）
    r"\s*[)）]"
)


def extract_position_shift_tag(text: Any) -> str:
    """提取岗位名中的班次标签。

    中文班次名归一化为单字（白/晚/夜/早/中）；
    字母/天干代号（A/B/C/D/甲/乙/丙/丁）保持原值返回，不做语义假设。

    例："东门门岗（晚）" → "晚"；"南门车岗(白班)" → "白"；
        "消控员 (A)" → "A"；"消控员 (B)" → "B"；"停车场" → ""。
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    match = _POSITION_SHIFT_TAG_RE.search(raw)
    if not match:
        return ""
    tag = match.group(1)
    if not tag:
        return ""
    # 中文班次名取首字归一化
    _CN_TAGS = {"白班": "白", "晚班": "晚", "夜班": "夜", "早班": "早", "中班": "中"}
    if tag in _CN_TAGS:
        return _CN_TAGS[tag]
    # 单字中文班次（白/晚/夜/早/中）直接返回
    if tag in ("白", "晚", "夜", "早", "中"):
        return tag
    # 字母/天干代号原样返回
    return tag


def position_name_with_shift_tag(text: Any) -> str:
    """在 strip_position_time_suffix 基础上保留班次标签，得到可精确挂接的岗位键。

    例："东门门岗（晚）7:00-19:00" → "东门门岗(晚)"；"停车场" → "停车场"。
    与 strip_position_time_suffix 结果不同时，说明该岗位带班次标签。
    """
    base = strip_position_time_suffix(text)
    tag = extract_position_shift_tag(text)
    return f"{base}({tag})" if tag else base


def normalize_position_name(text: Any) -> str:
    """将岗位名规范化为可精确匹配的形式。

    处理以下差异（这些差异不影响语义但会导致字符串 !=）：
    - 全角括号 → 半角括号
    - 连续空格 → 无空格
    - 括号内侧空格 → 去除
    - 全角空格 → 半角空格 → 去除

    例："消控员 (A)" → "消控员(A)"
        "内场安全员(B)" → "内场安全员(B)"
        "商场巡逻岗(白班）" → "商场巡逻岗(白班)"

    注意：此函数保留原始岗位名的全部信息（含括号、标签），
    不像 strip_position_time_suffix 那样删掉括号内容。
    用于全名精确匹配；聚合时仍用 strip 后的名称。
    """
    raw = str(text or "").strip()
    if not raw:
        return raw
    # 全角括号 → 半角
    result = raw.replace("（", "(").replace("）", ")")
    # 全角空格 → 半角
    result = result.replace("\u3000", " ")
    # 括号内侧空格去除
    result = re.sub(r"\(\s+", "(", result)
    result = re.sub(r"\s+\)", ")", result)
    # 连续空格 → 无空格
    result = re.sub(r"\s+", "", result)
    return result


def _norm_24h(time_text: str) -> str:
    """把 24:xx 归一为 00:xx（24:00 即次日零点）。

    strptime 不接受 24 小时制的 24（%H 范围 0-23），编制表里写成
    (24:00,4:00) 的窗口不归一化会在后续 parse_time_value 解析失败被静默跳过。
    """
    m = re.match(r"^24:(\d{2})$", time_text.strip())
    return f"00:{m.group(1)}" if m else time_text


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
            start_time = _norm_24h(match.group(1))
            end_time = _norm_24h(match.group(2))
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
SHORTAGE_MARKERS = {"缺岗", "旷工", "未到岗", "空岗", "缺编", "未到", "无故缺岗", "脱岗", "缺勤"}

# 「缺勤N」编号变体（排班员用它区分同日多岗缺勤）：缺勤1、缺勤2 ...
# 注意必须在 split_employee_cell 之前拦截，否则会被当成员工姓名
SHORTAGE_PATTERN = re.compile(r"^缺勤\d*$")
# 减岗标记（计划性减员：确定扣款，但仅按 1 倍日服务费，不乘缺编系数）
REDUCTION_MARKERS = {"减岗"}
# 「减岗N」编号变体，与缺勤N同理，必须在 split_employee_cell 之前拦截
REDUCTION_PATTERN = re.compile(r"^减岗\d*$")


def split_employee_cell(value: Any) -> list[str]:
    """把排班单元格拆成人员姓名列表。"""
    if value in (None, "", 0, "0"):
        return []
    text = str(value).strip()
    if not text or text in REST_MARKERS:
        return []
    for sep in ["\n", "、", "，", ",", ";", "；"]:
        text = text.replace(sep, " ")
    names: list[str] = []
    for part in text.split():
        part = part.strip()
        if not part or part in {"休息", "休", "0"}:
            continue
        part = re.sub(r"[（(].*?[)）]", "", part).strip()
        if part:
            names.append(part)
    return names


def classify_schedule_cell(raw: Any) -> dict:
    """把排班表的一个单元格识别为五种语义之一。

    返回 {"kind": "rest"|"leave"|"shortage"|"reduction"|"person", "names": [..], "raw": str}
    - rest    : 空 / 休息 / 未排班  → 当天该岗无人，不计入审核
    - leave   : 请假类            → 有正当原因，不计入缺岗、不扣款
    - shortage: 缺岗/旷工 等显式标记 → 确定缺岗，计入扣款侧（日服务费 × 缺编系数）
    - reduction: 减岗显式标记      → 确定扣款，但仅按 1 倍日服务费（不乘缺编系数）
    - person  : 人名              → 用排班姓名作探针，去 BI 反查当天是否打卡
    """
    text = "" if raw is None else str(raw).strip()
    if text == "" or text in REST_MARKERS:
        return {"kind": "rest", "names": [], "raw": text}
    if text in LEAVE_MARKERS:
        return {"kind": "leave", "names": [], "raw": text}
    if text in SHORTAGE_MARKERS or SHORTAGE_PATTERN.match(text):
        return {"kind": "shortage", "names": [], "raw": text}
    if text in REDUCTION_MARKERS or REDUCTION_PATTERN.match(text):
        return {"kind": "reduction", "names": [], "raw": text}
    names = split_employee_cell(text)
    if names:
        return {"kind": "person", "names": names, "raw": text}
    # 兜底：既非已知标记也非空，按休息忽略（避免脏数据污染审核）
    return {"kind": "rest", "names": [], "raw": text}


# --------------------------------------------------------------------------
# 异常确认：唯一「计入扣款」规则
# --------------------------------------------------------------------------
# 审核结果只有一份（audit_results 行），「已确认」(audit_results.status) 是它
# 是否已定稿的唯一判定依据。一条异常是否计入扣款，全系统（定稿重算、审核结果页、
# PDF 报告）只认下面这一条规则，不存在第二套口径：
#
#     未标记免扣 且 未被显式取消确认  →  计入
#
# 审核刚完成时结果里还没有 confirmations，因此全部异常默认计入（即审核时全量口径）；
# 异常确认写入 confirmed=false 或 free_deduction=true 后，该项即不再计入。
def confirm_key(exception_type: str, employee_name: str, work_date: str, window: str = "") -> str:
    """异常确认键：{类型}|{员工}|{日期}[|{窗口}]。"""
    if window:
        return f"{exception_type}|{employee_name}|{work_date}|{window}"
    return f"{exception_type}|{employee_name}|{work_date}"


def mid_clock_confirm(confirmations: dict, employee_name: str, work_date: str, window: str = "") -> dict:
    """中间卡缺失按「漏打卡」口径取确认记录（并兼容历史写入的 mid_clock| 键）。"""
    return (
        confirmations.get(confirm_key("missing_clock", employee_name, work_date, window))
        or confirmations.get(confirm_key("mid_clock", employee_name, work_date, window))
        or {}
    )


def is_charged(conf: dict) -> bool:
    """唯一扣款判定规则：未免扣 且 未被取消确认 → 计入。"""
    return bool(conf.get("confirmed", True)) and not bool(conf.get("free_deduction", False))


def recompute_audit_totals(data: dict) -> None:
    """按唯一「计入」规则就地重算审核结果的金额与计数（全系统唯一定稿口径）。

    只改这一份结果的金额/计数，不产生任何副本；单位价取自
    s04_rules.missing_clock_amount（不可变的合同规则值），因此对同一份结果
    重复执行不会产生漂移（幂等）。审核结果页与 PDF 报告读的都是这里写下的值。
    """
    s04 = data.get("s04_attendance_audit", {}) or {}
    rule_cfg = s04.get("s04_rules", {}) or {}
    unit = float(rule_cfg.get("missing_clock_amount", 0) or 0)
    details = s04.get("deduction_details", []) or []

    for detail in details:
        emp = detail.get("employee_name", "")
        confs = detail.get("confirmations", {}) or {}

        # 漏打卡（中间卡缺失并入同口径）
        missing_count = sum(
            1
            for d in (detail.get("missing_clock_dates", []) or [])
            if is_charged(confs.get(confirm_key("missing_clock", emp, d), {}))
        ) + sum(
            int(issue.get("missing", 0) or 0)
            for issue in (detail.get("mid_clock_issues", []) or [])
            if is_charged(mid_clock_confirm(confs, emp, issue.get("date", ""), issue.get("window", "")))
        )
        detail["missing_clock_count"] = missing_count
        detail["missing_clock_amount"] = round(unit * missing_count, 2)

        late_charged = [
            late
            for late in (detail.get("late_details", []) or [])
            if float(late.get("amount", 0) or 0) > 0  # S04-1 已转漏打卡的不重复计数
            and is_charged(confs.get(confirm_key("late", emp, late.get("date", "")), {}))
        ]
        detail["late_count"] = len(late_charged)
        detail["late_total"] = round(sum(float(late.get("amount", 0) or 0) for late in late_charged), 2)

        early_charged = [
            early
            for early in (detail.get("early_leave_details", []) or [])
            if float(early.get("amount", 0) or 0) > 0  # S04-1 已转漏打卡的不重复计数
            and is_charged(confs.get(confirm_key("early_leave", emp, early.get("date", "")), {}))
        ]
        detail["early_leave_count"] = len(early_charged)
        detail["early_leave_total"] = round(sum(float(early.get("amount", 0) or 0) for early in early_charged), 2)

        absence_multiplier_val = float(
            detail.get("absence_multiplier") or rule_cfg.get("absence_penalty_multiplier") or 1.0
        )
        base_rate = float(detail.get("absence_daily_rate", 0) or 0)
        # 星期分段班次的按日费率（审核时写入 absence_records[].daily_rate；
        # 历史数据无此字段时回退单一费率，结果与旧口径一致）
        rate_by_date = {}
        for _r in (detail.get("absence_records", []) or []):
            if _r.get("date") and _r.get("daily_rate") is not None:
                rate_by_date[_r["date"]] = float(_r.get("daily_rate") or 0)
        absence_count = 0
        absence_amount = 0
        for d in (detail.get("absence_dates", []) or []):
            if is_charged(confs.get(confirm_key("absence", emp, d), {})):
                absence_count += 1
                # 每天最终扣款取整到元（四舍五入），与审核时/前端显示口径一致，
                # 保证各行显示之和与总额恒等
                absence_amount += round_money(rate_by_date.get(d, base_rate) * absence_multiplier_val)
        detail["absence_count"] = absence_count
        detail["absence_amount"] = round(absence_amount, 2)

        detail["total_deduction"] = round(
            detail["missing_clock_amount"]
            + detail["late_total"]
            + detail["early_leave_total"]
            + detail["absence_amount"],
            2,
        )

    total_missing = round(sum(d["missing_clock_amount"] for d in details), 2)
    total_late = round(sum(d["late_total"] for d in details), 2)
    total_early = round(sum(d["early_leave_total"] for d in details), 2)
    total_absence = round(sum(d["absence_amount"] for d in details), 2)
    s04["summary"] = {
        "total_missing_clock_amount": total_missing,
        "total_late_amount": total_late,
        "total_early_leave_amount": total_early,
        "total_absence_amount": total_absence,
        "total_deduction": round(total_missing + total_late + total_early + total_absence, 2),
        "affected_employees": len([d for d in details if d["total_deduction"] > 0]),
        "overtime_warning_count": (s04.get("summary", {}) or {}).get("overtime_warning_count", 0),
    }
    data["s04_attendance_audit"] = s04
