"""S04 考勤管理扣款审核（人员级）。

签到表（Sheet3）单元格四态 → 审核分流：
- "缺岗"：确定缺勤，不比对考勤，直接记 S04-4 缺勤扣款
- 人名：人来了，比对 BI 考勤打卡，检查上下班卡与中间卡
- 休息/空：当天该岗无人，跳过
- 请假：有正当原因，不扣款

比对 BI 考勤后（迟到/早退的时间档位与扣款金额全部从合同细则动态读取，不在代码中
硬编码任何阈值或金额）：
- S04-1 漏打卡：当月无打卡记录 / 迟到早退超过合同阈值（late_early_over_minutes_as_absence）
  / 中间卡缺失，超出免扣次数后按合同 missing_clock_deduction 金额扣款
- 迟到/早退分档：按合同细则 late_early_tiers 中各档 max_minutes 升序匹配，
  命中哪个区间就使用该区间配置的 amount，支持合同方配置的任意档数
- S04-4 缺勤：签到表标记"缺岗"，按当日服务费 × 合同缺编系数（contract_deduction_coefficient）扣款
  （未配置时按 1.0 处理；与槽位缺编扣款使用同一系数，来源一致）

中间卡规则：
- 带括号的中间卡时段 (12:00-13:00) → 打 1 次卡，缺失记漏打卡 1 次
- 不带括号的中间卡时段 12:00-13:00 → 打 2 次卡，缺几次记漏打卡几次

班次按周几分段：合同可写"周一至周四7:00-21:30;周五至周日7:00-22:00"，
审核时按当天星期选取对应班次。BI 考勤表无星期，由代码根据日期计算。

上游立场：扣的是外包公司的钱，不追问个人原因。
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.api.v2.models.position_models import PositionInfo
from app.api.v2.utils.audit_common import (
    normalize_employee_name,
    parse_position_shifts,
    get_shift_for_date,
    parse_time_value,
    time_to_minutes,
    parse_mid_clock_time,
    resolve_cross_midnight,
    daily_service_fee,
)


def _norm_month(audit_month: str) -> str:
    s = str(audit_month or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})[-年.]?(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return s


def _bi_day_to_iso(label: Any, audit_month: str) -> str:
    text = str(label or "").strip()
    # 支持完整 ISO 日期标签（如 "2026-09-01"），用于跨月合并
    m_iso = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    day = int(digits[-2:]) if len(digits) >= 2 else int(digits)
    m_am = re.match(r"(\d{4})-?(\d{2})", str(audit_month or ""))
    if m_am:
        prefix = f"{m_am.group(1)}-{m_am.group(2)}"
    else:
        prefix = str(audit_month or "")
    return f"{prefix}-{day:02d}"


def _next_date(iso_date: str) -> str:
    """计算 ISO 日期的下一天。"""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _parse_clock_times(clock_list) -> list[str]:
    if not isinstance(clock_list, list):
        clock_list = [str(clock_list)] if clock_list else []
    result = []
    for entry in clock_list:
        for t in str(entry).split("\n"):
            t = t.strip()
            if t:
                result.append(t)
    return result


def _calc_shift_minutes(shift_start: str, shift_end: str) -> float:
    """计算单段班次的工时（分钟），用 shift_start/shift_end 解析后做差。

    跨天班次（end <= start，如 22:00-06:00）自动补 24h。
    返回分钟数；无法解析时返回 0。
    """
    s_min = time_to_minutes(parse_time_value(shift_start))
    e_min = time_to_minutes(parse_time_value(shift_end))
    if s_min is None or e_min is None:
        return 0.0
    diff = e_min - s_min
    if diff <= 0:
        diff += 24 * 60  # 跨天班次
    return float(diff)


def _calc_daily_total_hours(sched_list: list[dict]) -> float:
    """计算某人在某日的排班总工时（小时），累加所有排班条目的工时。

    每条排班条目已有 shift_start / shift_end（由 _build_schedule_index 保存）。
    """
    total_minutes = 0.0
    for s in sched_list:
        total_minutes += _calc_shift_minutes(s.get("shift_start", ""), s.get("shift_end", ""))
    return round(total_minutes / 60.0, 2)


# 工时异常判定阈值：单日排班总工时超过此值 → 告警（仅告警，不扣款）
OVERTIME_THRESHOLD_HOURS = 20.0


def _apply_late_early(entry: dict, late: float, early: float, s04_sub: list,
                      work_date: str, sched: dict, clock_display: list, all_clocks: list):
    """将迟到/早退结果写入员工记录（单班次与拆分班次共用）。

    S04-1（超过合同阈值）同时写入 missing_clock_dates 和对应明细，
    确保前端"漏打卡"里能看到迟到/早退原因。
    """
    _over = _late_over_threshold(s04_sub)
    _over_label = f">{_over}min" if _over is not None else "超时"
    if late > 0:
        tier, amount = _classify_late_early(late, s04_sub)
        if tier == "S04-1":
            entry["missing_clock_dates"].add(work_date)
            if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
                entry["missing_clock_records"].append({
                    "date": work_date, "position": sched["position"],
                    "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                    "clock_times": list(clock_display),
                    "missing_type": f"迟到{_over_label}转S04-1",
                })
            entry["late_details"].append({
                "date": work_date, "position": sched["position"],
                "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                "clock_in": all_clocks[0] if all_clocks else "",
                "clock_times": list(clock_display),
                "minutes": late, "tier": tier, "amount": amount,
            })
        else:
            entry["late_details"].append({
                "date": work_date, "position": sched["position"],
                "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                "clock_in": all_clocks[0] if all_clocks else "",
                "clock_times": list(clock_display),
                "minutes": late, "tier": tier, "amount": amount,
            })
    if early > 0:
        tier, amount = _classify_late_early(early, s04_sub)
        if tier == "S04-1":
            entry["missing_clock_dates"].add(work_date)
            if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
                entry["missing_clock_records"].append({
                    "date": work_date, "position": sched["position"],
                    "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                    "clock_times": list(clock_display),
                    "missing_type": f"早退{_over_label}转S04-1",
                })
            entry["early_leave_details"].append({
                "date": work_date, "position": sched["position"],
                "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                "clock_out": all_clocks[-1] if all_clocks else "",
                "clock_times": list(clock_display),
                "minutes": early, "tier": tier, "amount": amount,
            })
        else:
            entry["early_leave_details"].append({
                "date": work_date, "position": sched["position"],
                "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                "clock_out": all_clocks[-1] if all_clocks else "",
                "clock_times": list(clock_display),
                "minutes": early, "tier": tier, "amount": amount,
            })


def _check_missing_clockout(entry: dict, is_cross: bool, clocks: list, next_clocks: list,
                             all_clocks: list, work_date: str, sched: dict, clock_display: list):
    """检查漏打卡（单班次与拆分班次共用）。

    跨夜班次：
    - 缺下班卡：当日有上班卡但次日无下班卡
    - 缺上班卡：当日无上班卡（clocks 为空）
    非跨夜班次：
    - 只有1次打卡 → 既缺上班也缺下班，记为漏打卡
    """
    has_missing = False
    missing_type = ""
    if is_cross:
        if not clocks:
            has_missing = True
            missing_type = "缺上班卡"
        elif clocks and not next_clocks:
            has_missing = True
            missing_type = "缺下班卡"
    else:
        if len(all_clocks) == 1:
            has_missing = True
            missing_type = "缺下班卡"
    if has_missing:
        entry["missing_clock_dates"].add(work_date)
        if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
            entry["missing_clock_records"].append({
                "date": work_date, "position": sched["position"],
                "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                "clock_times": list(clock_display),
                "missing_type": missing_type,
            })


def extract_s04_rules(contract_rules) -> dict | None:
    if not contract_rules:
        return None
    # 如果是 dict，直接返回（已经是 S04 规则）
    if isinstance(contract_rules, dict):
        return contract_rules
    # 如果是 list，查找 code="S04" 的规则
    if isinstance(contract_rules, list):
        for rule in contract_rules:
            if isinstance(rule, dict) and rule.get("code") == "S04":
                return rule
    return None


# 缺勤/缺岗扣款复用合同里的"缺编系数"（contract_deduction_coefficient）。
# 该系数同时作用于 S04-4 缺岗（日服务费 × N）和槽位缺编扣款。
def get_absence_coefficient(s04_rules: dict | None) -> float:
    """从合同规则里取缺编/缺岗扣款倍数（合同字段 contract_deduction_coefficient）。

    未配置或非正值时按 1.0 处理（= 仅扣日服务费，不加倍）。
    """
    if not isinstance(s04_rules, dict):
        return 1.0
    value = s04_rules.get("contract_deduction_coefficient")
    try:
        coef = float(value)
    except (TypeError, ValueError):
        return 1.0
    return coef if coef > 0 else 1.0


def _build_schedule_index(position_infos: list[PositionInfo]) -> tuple[dict[tuple[str, str], list[dict]], dict[tuple[str, str], dict]]:
    """构建 (姓名, 日期) → [排班信息列表] 索引，以及 (岗位, 日期) → 缺岗信息 索引。

    关键逻辑：
    - 班次时间按周几分段解析（parse_shift_by_weekday），再根据每个日期的星期
      用 get_shift_for_date 选取当天对应班次。
    - "缺岗"单元格无论班次能否解析都收入 vacancies（签到表写缺岗=确定缺勤）。
    - 人名单元格同样不因班次解析失败而跳过（人来了就纳入比对）。
    - 同一天同一人出现在多个岗位时，所有候选班次都保留（list 追加，不覆盖）。
    """
    index: dict[tuple[str, str], list[dict]] = {}
    # 键带槽位身份（岗位, 槽位标识, 日期）：同名岗位（如商业保洁 40 个「保洁」岗）
    # 同日多槽位缺岗必须各自独立计数，否则按 (岗位,日期) 聚合会坍缩成一条、少扣款
    vacancies: dict[tuple[str, str, str], dict] = {}
    for pi in position_infos:
        for p in pi.positions:
            shifts = parse_position_shifts(p.position_name, p.shift_time)
            mid_clock_windows = parse_mid_clock_time(p.mid_clock_time)
            for slot in p.slots:
                for work_date, cells in slot.daily.items():
                    start, end = get_shift_for_date(shifts, work_date)
                    # 跨夜判定：编制表 cross_midnight 字段优先；字段未明确（非「是」）时，
                    # 回退到班次时间数值关系（开始时间数值 > 结束时间数值 → 跨夜）。
                    auto_cross = resolve_cross_midnight(p.cross_midnight_raw, start, end)
                    for cell in cells:
                        status = cell.get("status", "")
                        if status == "缺岗":
                            # 槽位标识必须含 slot_index：同岗位同区域的多槽位
                            # （如南京金鹰世界 13 个「写字楼楼层保洁」槽位区域全是
                            # 「ABC开放楼层区域」）仅用区域会再次坍缩成一条
                            slot_ident = f"{slot.area}#{slot.slot_index}" if slot.area else f"槽位{slot.slot_index}"
                            key = (p.position_name, slot_ident, work_date)
                            if key not in vacancies:
                                vacancies[key] = {
                                    "shift_start": start,
                                    "shift_end": end,
                                    "position": p.position_name,
                                    "slot_ident": slot_ident,
                                    "hourly_rate": p.hourly_rate,
                                    "daily_hours": p.daily_hours,
                                    "monthly_total": p.monthly_total,
                                    "actual_count": p.actual_count,
                                    "service_type": pi.service_type,
                                    "is_cross_midnight": auto_cross,
                                    "mid_clock_windows": mid_clock_windows,
                                }
                            continue
                        for name in cell.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                entry = {
                                    "shift_start": start,
                                    "shift_end": end,
                                    "position": p.position_name,
                                    "hourly_rate": p.hourly_rate,
                                    "daily_hours": p.daily_hours,
                                    "monthly_total": p.monthly_total,
                                    "actual_count": p.actual_count,
                                    "service_type": pi.service_type,
                                    "is_cross_midnight": auto_cross,
                                    "mid_clock_windows": mid_clock_windows,
                                }
                                key = (nn, work_date)
                                if key not in index:
                                    index[key] = []
                                index[key].append(entry)
    return index, vacancies

def _build_bi_index(bi_records: list[dict], audit_month: str) -> dict[tuple[str, str], list[str]]:
    index: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rec in bi_records:
        name = normalize_employee_name(rec.get("employee_name", ""))
        if not name:
            continue
        att = rec.get("attendance", {}) or {}
        for day_label, clocks in att.items():
            iso = _bi_day_to_iso(day_label, audit_month)
            if not iso:
                continue
            index[(name, iso)].extend(_parse_clock_times(clocks or []))
    return index


def _calc_late_early_minutes(
    clock_times: list[str],
    shift_start: str,
    shift_end: str,
    is_cross_midnight: bool,
) -> tuple[int, int]:
    if not clock_times:
        return 0, 0

    start_min = time_to_minutes(parse_time_value(shift_start))
    end_min = time_to_minutes(parse_time_value(shift_end))
    if start_min is None or end_min is None:
        return 0, 0

    # 跨夜缓冲窗口 = 班次时长的 50%
    _shift_mins = abs(end_min - start_min)
    if _shift_mins <= 0:
        _shift_mins += 1440
    _cross_buf = int(_shift_mins * 0.5)

    clock_mins = []
    for t in clock_times:
        m = time_to_minutes(parse_time_value(t))
        if m is not None:
            if is_cross_midnight and m < start_min and m <= end_min + _cross_buf:
                m += 1440
            clock_mins.append(m)

    if not clock_mins:
        return 0, 0

    clock_mins.sort()
    actual_in = clock_mins[0]
    actual_out = clock_mins[-1]

    late = max(0, actual_in - start_min)
    if is_cross_midnight and end_min <= start_min:
        # 注意必须 >=1440：次日 00:00:xx 的卡 time_to_minutes=0，+1440 后恰好等于 1440，
        # 用 >1440 会漏掉这一临界（不取模 → early=end-1440 为负 → 误判为无早退），
        # 导致"次日只有 00:00 附近一张卡（实为中卡）、真正下班卡缺失"的班次漏判。
        actual_out = actual_out % 1440 if actual_out >= 1440 else actual_out
        early = max(0, end_min - actual_out)
    else:
        early = max(0, end_min - actual_out)

    return late, early


# --------------------------------------------------------------------------
# 迟到/早退分档（阈值与金额全部来自合同细则，不做任何硬编码）
# --------------------------------------------------------------------------
def _as_positive_int(value: Any) -> int | None:
    """将配置值解析为正整数分钟数；无法解析或非正数时返回 None。"""
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _as_amount(value: Any) -> int | None:
    """将配置值解析为非负金额；公式类字符串（如「当日服务费*2.5」）返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value >= 0 else None
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return int(v) if v >= 0 else None


def _is_late_early_tier(sub: Any) -> bool:
    """判断一条子规则是否为迟到/早退扣款档位（须同时具备 max_minutes 与 amount）。"""
    if not isinstance(sub, dict):
        return False
    if str(sub.get("code", "")) in ("S04-1", "S04-4"):
        return False
    return _as_positive_int(sub.get("max_minutes")) is not None and _as_amount(sub.get("amount")) is not None


def _late_tier_code(index: int) -> str:
    """迟到/早退档位代码：前两档沿用 S04-2/S04-3（兼容既有前端展示），
    更多档位自 S04-5 起顺延（S04-4 已被「缺岗」占用）。"""
    if index == 0:
        return "S04-2"
    if index == 1:
        return "S04-3"
    return f"S04-{index + 3}"


def _parse_minutes_from_text(text: Any) -> int | None:
    """从档位名称文本中解析分钟阈值：「在30分钟以内」→30，「1小时以内」→60。"""
    s = str(text or "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*小时", s)
    if m:
        return int(float(m.group(1)) * 60)
    m = re.search(r"(\d+)\s*分钟", s)
    if m:
        return int(m.group(1))
    if "半小时" in s:
        return 30
    return None


def _late_over_threshold(s04_sub_rules: list[dict]) -> int | None:
    """「迟到/早退超过该分钟数转缺勤（S04-1）」的阈值。

    优先取 S04-1 条目的 max_minutes（即合同字段 late_early_over_minutes_as_absence）；
    未配置时退化为最高迟到档位的 max_minutes（超出最高档即转缺勤）。
    """
    over = None
    last_max = None
    for sub in s04_sub_rules or []:
        if not isinstance(sub, dict):
            continue
        v = _as_positive_int(sub.get("max_minutes"))
        if v is None:
            continue
        if str(sub.get("code", "")) == "S04-1":
            over = v
        elif last_max is None or v > last_max:
            last_max = v
    return over if over is not None else last_max


def _classify_late_early(minutes: int, s04_sub_rules: list[dict]) -> tuple[str, int]:
    """按合同细则配置的时间档位判定迟到/早退扣款。

    档位（阈值 max_minutes 与金额 amount）完全来自合同细则：
    - s04_sub_rules 中除 S04-1（转缺勤/漏打卡）外、同时具备 max_minutes 与 amount
      的条目视为迟到/早退档位，按 max_minutes 升序匹配，命中即返回该档金额；
    - 分钟数超过 S04-1 阈值（缺省时为最高档位上限）→ 返回 ("S04-1", 0)；
    - 分钟数未超 S04-1 阈值但超过所有档位上限 → 归入最高档（最后一档区间延伸至阈值）。

    兜底：合同细则未配置任何有效档位时返回 ("", 0) 并打印告警——不使用任何
    硬编码默认值，避免在配置缺失时产生错误扣款。
    """
    if minutes <= 0:
        return "", 0

    tiers = sorted(
        (
            {
                "code": str(sub.get("code", "")),
                "max_minutes": _as_positive_int(sub.get("max_minutes")),
                "amount": _as_amount(sub.get("amount")),
            }
            for sub in (s04_sub_rules or [])
            if _is_late_early_tier(sub)
        ),
        key=lambda t: t["max_minutes"],
    )
    if not tiers:
        print(f"  [告警] 合同细则未配置迟到/早退分档，{minutes} 分钟不执行扣款")
        return "", 0

    over_minutes = _late_over_threshold(s04_sub_rules)
    if over_minutes is not None and minutes > over_minutes:
        return "S04-1", 0

    for t in tiers:
        if minutes <= t["max_minutes"]:
            return t["code"], t["amount"]
    last = tiers[-1]
    return last["code"], last["amount"]


def _check_mid_clock_compliance(
    clock_times: list[str],
    mid_clock_windows: list[tuple[str, str, int]],
    shift_start: str,
    shift_end: str,
    is_cross_midnight: bool,
) -> dict:
    """检查中间卡打卡合规性。

    返回:
    {
        "clock_in_ontime": bool,      # 上班卡是否在班次开始前
        "clock_out_ontime": bool,     # 下班卡是否在班次结束后
        "mid_clock_issues": [...],    # 中间卡缺失详情
        "total_required_clocks": int, # 总要求打卡次数（上班+中间+下班）
        "actual_clock_count": int,    # 实际打卡次数
    }
    """
    result = {
        "clock_in_ontime": True,
        "clock_out_ontime": True,
        "mid_clock_issues": [],
        "total_required_clocks": 2,  # 上班 + 下班
        "actual_clock_count": len(clock_times),
        "total_missing_mid_clocks": 0,
    }

    if not clock_times:
        return result

    start_min = time_to_minutes(parse_time_value(shift_start))
    end_min = time_to_minutes(parse_time_value(shift_end))
    if start_min is None or end_min is None:
        return result

    # 跨夜缓冲窗口 = 班次时长的 50%
    _shift_mins = abs(end_min - start_min)
    if _shift_mins <= 0:
        _shift_mins += 1440
    _cross_buf = int(_shift_mins * 0.5)

    clock_mins = []
    for t in clock_times:
        m = time_to_minutes(parse_time_value(t))
        if m is not None:
            if is_cross_midnight and m < start_min and m <= end_min + _cross_buf:
                m += 1440
            clock_mins.append(m)

    if not clock_mins:
        return result

    clock_mins.sort()
    actual_in = clock_mins[0]
    actual_out = clock_mins[-1]

    # 检查上班卡：应该在班次开始前或刚好开始
    result["clock_in_ontime"] = actual_in <= start_min

    # 检查下班卡：应该在班次结束后或刚好结束
    if is_cross_midnight and end_min <= start_min:
        result["clock_out_ontime"] = actual_out >= end_min or actual_out >= end_min + 1440
    else:
        result["clock_out_ontime"] = actual_out >= end_min

    # 检查中间卡
    for window_start, window_end, required_count in mid_clock_windows:
        ws_min = time_to_minutes(parse_time_value(window_start))
        we_min = time_to_minutes(parse_time_value(window_end))
        if ws_min is None or we_min is None:
            continue

        # 跨夜窗口（大数在前小数在后，如 23:00-01:00）：在午夜处拆成两段，
        # 前半段对应当天晚上、后半段对应次日凌晨。
        # 调用方已把当天/次日打卡分别按班次过滤后传入（当天 ≥ 上班时间-缓冲，
        # 次日 ≤ 下班时间+缓冲），同一时刻值不存在两种归属，直接用原始时刻比较即可。
        if ws_min > we_min:
            ranges = ((ws_min, 1439), (0, we_min))
        else:
            ranges = ((ws_min, we_min),)

        # 计算该时间段内的打卡次数
        actual_count = 0
        for t in clock_times:
            m = time_to_minutes(parse_time_value(t))
            if m is not None and any(a <= m <= b for a, b in ranges):
                actual_count += 1

        if actual_count < required_count:
            missing = required_count - actual_count
            result["mid_clock_issues"].append({
                "window": f"{window_start}-{window_end}",
                "required": required_count,
                "actual": actual_count,
                "missing": missing,
            })
            result["total_required_clocks"] += required_count
            result["total_missing_mid_clocks"] += missing

    return result


def run_attendance_s04_audit(
    position_infos: list[PositionInfo],
    bi_records: list[dict],
    s04_rules: dict | None,
    audit_month: str,
) -> dict:
    month = _norm_month(audit_month)
    
    # 兼容两种格式：dict 直接存储规则，或 list 包含 sub_rules
    if s04_rules and "sub_rules" in s04_rules:
        raw_sub = s04_rules.get("sub_rules", [])
        # 为迟到/早退档位补全 max_minutes（缺失时从档位名称文本解析，如「在30分钟以内」→30），
        # 阈值与金额均以合同细则为准，无效档位直接跳过，不使用任何默认值。
        s04_sub = []
        for sub in raw_sub:
            if not isinstance(sub, dict):
                continue
            code = str(sub.get("code", ""))
            if code in ("S04-1", "S04-4"):
                s04_sub.append(sub)
                continue
            max_min = _as_positive_int(sub.get("max_minutes"))
            if max_min is None:
                max_min = _parse_minutes_from_text(sub.get("name", ""))
            amount = _as_amount(sub.get("amount"))
            if max_min is None or amount is None:
                print(f"  [告警] 合同细则中档位 {sub.get('name') or code} 缺少有效阈值/金额，已跳过")
                continue
            s04_sub.append({**sub, "max_minutes": max_min, "amount": amount})
        s04_1 = next((r for r in s04_sub if r.get("code") == "S04-1"), None)
        missing_free = int(s04_1.get("free_limit", 3)) if s04_1 else 3
        missing_amount = int(s04_1.get("amount", 50)) if s04_1 else 50
        s04_4 = next((r for r in s04_sub if r.get("code") == "S04-4"), None)
    elif s04_rules:
        # dict 格式：直接从顶层字段取值，并构建 s04_sub
        missing_free = int(s04_rules.get("missing_clock_free_times_per_month", 3))
        missing_amount = int(s04_rules.get("missing_clock_deduction", 50))
        # 如果有 late_early_over_minutes_as_absence 字段，说明支持缺勤判定
        s04_4 = {"code": "S04-4"} if "late_early_over_minutes_as_absence" in s04_rules else None
        # 构建 s04_sub 用于 _classify_late_early：档数任意，阈值/金额全部取自合同细则，
        # 缺 max_minutes 或 amount 的档位视为无效并跳过（不填默认值）。
        # 先按 max_minutes 升序再分配档位代码，保证合同录入乱序时代码仍与阈值一致。
        late_early_tiers = s04_rules.get("late_early_tiers", [])
        valid_tiers = []
        for i, t in enumerate(late_early_tiers):
            if not isinstance(t, dict):
                continue
            max_min = _as_positive_int(t.get("max_minutes"))
            amount = _as_amount(t.get("amount"))
            if max_min is None or amount is None:
                print(f"  [告警] 合同细则迟到/早退第 {i + 1} 档缺少有效阈值或金额，已跳过：{t}")
                continue
            valid_tiers.append({"max_minutes": max_min, "amount": amount})
        valid_tiers.sort(key=lambda t: t["max_minutes"])
        s04_sub = [
            {"code": _late_tier_code(i), "amount": t["amount"], "max_minutes": t["max_minutes"]}
            for i, t in enumerate(valid_tiers)
        ]
        over_minutes = _as_positive_int(s04_rules.get("late_early_over_minutes_as_absence"))
        if over_minutes is not None:
            s04_sub.append({"code": "S04-1", "amount": 0, "max_minutes": over_minutes})
    else:
        missing_free = 3
        missing_amount = 50
        s04_4 = None
        s04_sub = []

    # 缺勤/缺岗扣款倍数：日服务费 × 缺编系数（合同字段 contract_deduction_coefficient）
    absence_multiplier = get_absence_coefficient(s04_rules)

    schedule_index, vacancies = _build_schedule_index(position_infos)
    bi_index = _build_bi_index(bi_records, month)

    employee_data: dict[str, dict] = {}

    for (name, work_date), sched_list in schedule_index.items():
        # 工时异常检测：同人同日多条排班时，先算单日总工时
        # — 合法拆分（上午+下午）且总工时正常 → 正常审核，不告警
        # — 总工时 > 20h（含非法拆分叠加）→ 工时异常告警，当天跳过扣款
        if len(sched_list) > 1:
            total_hours = _calc_daily_total_hours(sched_list)
            entry = employee_data.setdefault(name, {
                "employee_name": name,
                "position": sched_list[0]["position"],
                "missing_clock_dates": set(),
                "missing_clock_records": [],
                "missing_clock_count_extra": 0,
                "late_details": [],
                "early_leave_details": [],
                "absence_dates": set(),
                "absence_records": [],
                "mid_clock_issues": [],
                "daily_rate": daily_service_fee(sched_list[0]["hourly_rate"], sched_list[0]["daily_hours"],
                                                 sched_list[0].get("monthly_total"), sched_list[0].get("actual_count"),
                                                 sched_list[0].get("service_type")),
                "overtime_warnings": [],
            })
            positions = [s["position"] for s in sched_list]
            if total_hours > OVERTIME_THRESHOLD_HOURS:
                entry["overtime_warnings"].append({
                    "date": work_date,
                    "positions": positions,
                    "total_hours": total_hours,
                    "message": f"{name} 在 {work_date} 单日排班工时 {total_hours}h（超 {OVERTIME_THRESHOLD_HOURS}h），当天不执行考勤扣款",
                })
                print(f"  [工时异常] {name} {work_date}: 总工时 {total_hours}h, 岗位 {'、'.join(positions)}")
                continue
            else:
                # 合法拆分班次：总工时正常，逐条审核每段排班的打卡
                for sched in sched_list:
                    clocks = list(bi_index.get((name, work_date), []))
                    is_cross = sched.get("is_cross_midnight", False)
                    _s_min = time_to_minutes(parse_time_value(sched["shift_start"]))
                    _e_min = time_to_minutes(parse_time_value(sched["shift_end"]))
                    if is_cross:
                        next_dt = _next_date(work_date)
                        next_clocks = list(bi_index.get((name, next_dt), [])) if next_dt else []
                        # 缓冲窗口 = 班次时长的 50%，确保加班/延迟下班不被误丢
                        _shift_mins = abs(_e_min - _s_min) if (_s_min is not None and _e_min is not None) else 720
                        if _shift_mins <= 0:
                            _shift_mins += 1440  # 跨天班次
                        _buf = int(_shift_mins * 0.5)
                        if _s_min is not None:
                            _s_buf = max(0, _s_min - _buf)
                            # 显式判 None：time_to_minutes 对 00:00:xx 返回 0（falsy），
                            # 不能用 or 兜底，否则零点整的合法打卡会被误丢
                            clocks = [t for t in clocks
                                      if (m := time_to_minutes(parse_time_value(t))) is not None and m >= _s_buf]
                        if _e_min is not None:
                            _e_buf = _e_min + _buf
                            next_clocks = [t for t in next_clocks
                                           if (m := time_to_minutes(parse_time_value(t))) is not None and m <= _e_buf]
                    else:
                        next_dt = ""
                        next_clocks = []

                    def _sort_key(t: str) -> int:
                        v = parse_time_value(t)
                        m = time_to_minutes(v) if v else 0
                        return m if m is not None else 0

                    clock_display: list[str] = []
                    if clocks:
                        clock_display.extend(sorted(clocks, key=_sort_key))
                    if next_clocks:
                        clock_display.extend([f"{next_dt} {t}" for t in sorted(next_clocks, key=_sort_key)])

                    all_clocks = clocks + next_clocks
                    mid_clock_windows = sched.get("mid_clock_windows", [])
                    emp = employee_data.setdefault(name, {
                        "employee_name": name,
                        "position": sched["position"],
                        "missing_clock_dates": set(),
                        "missing_clock_records": [],
                        "missing_clock_count_extra": 0,
                        "late_details": [],
                        "early_leave_details": [],
                        "absence_dates": set(),
                        "absence_records": [],
                        "mid_clock_issues": [],
                        "daily_rate": daily_service_fee(sched["hourly_rate"], sched["daily_hours"],
                                                         sched.get("monthly_total"), sched.get("actual_count"),
                                                         sched.get("service_type")),
                        "overtime_warnings": entry.get("overtime_warnings", []),
                    })

                    if not all_clocks:
                        emp["absence_dates"].add(work_date)
                        emp["absence_records"].append({
                            "date": work_date, "position": sched["position"],
                            "shift_start": sched["shift_start"], "shift_end": sched["shift_end"],
                            "clock_times": [],
                        })
                        continue

                    if mid_clock_windows:
                        mid_compliance = _check_mid_clock_compliance(
                            all_clocks, mid_clock_windows, sched["shift_start"], sched["shift_end"], is_cross)
                        if mid_compliance["mid_clock_issues"]:
                            for issue in mid_compliance["mid_clock_issues"]:
                                emp["mid_clock_issues"].append({**issue, "date": work_date, "position": sched["position"], "shift_start": sched["shift_start"], "shift_end": sched["shift_end"], "clock_times": list(clock_display)})
                            emp["missing_clock_count_extra"] += mid_compliance["total_missing_mid_clocks"]

                    late, early = _calc_late_early_minutes(all_clocks, sched["shift_start"], sched["shift_end"], is_cross)
                    _apply_late_early(emp, late, early, s04_sub, work_date, sched, clock_display, all_clocks)
                    _check_missing_clockout(emp, is_cross, clocks, next_clocks, all_clocks, work_date, sched, clock_display)
                continue

        sched = sched_list[0]
        clocks = list(bi_index.get((name, work_date), []))
        is_cross = sched.get("is_cross_midnight", False)

        # 跨天班次：合并次日的打卡数据（夜班 20:00-08:00 跨两天）
        next_dt = ""
        next_clocks: list[str] = []
        if is_cross:
            next_dt = _next_date(work_date)
            if next_dt:
                next_clocks = list(bi_index.get((name, next_dt), []))

            # 跨天班次过滤：只保留属于当前班次的打卡
            _s_min = time_to_minutes(parse_time_value(sched["shift_start"]))
            _e_min = time_to_minutes(parse_time_value(sched["shift_end"]))
            # 缓冲窗口 = 班次时长的 50%，确保加班/延迟下班不被误丢
            _shift_mins = abs(_e_min - _s_min) if (_s_min is not None and _e_min is not None) else 720
            if _shift_mins <= 0:
                _shift_mins += 1440  # 跨天班次
            _buf = int(_shift_mins * 0.5)
            if _s_min is not None:
                _s_buf = max(0, _s_min - _buf)
                # 显式判 None：time_to_minutes 对 00:00:xx 返回 0（falsy），
                # 不能用 or 兜底，否则零点整的合法打卡会被误丢
                clocks = [t for t in clocks
                          if (m := time_to_minutes(parse_time_value(t))) is not None and m >= _s_buf]
            if _e_min is not None:
                _e_buf = _e_min + _buf
                next_clocks = [t for t in next_clocks
                               if (m := time_to_minutes(parse_time_value(t))) is not None and m <= _e_buf]

        def _sort_key(t: str) -> int:
            v = parse_time_value(t)
            m = time_to_minutes(v) if v else 0
            return m if m is not None else 0

        clock_display: list[str] = []
        if clocks:
            clock_display.extend(sorted(clocks, key=_sort_key))
        if next_clocks:
            clock_display.extend([f"{next_dt} {t}" for t in sorted(next_clocks, key=_sort_key)])

        all_clocks = clocks + next_clocks
        mid_clock_windows = sched.get("mid_clock_windows", [])
        entry = employee_data.setdefault(name, {
            "employee_name": name,
            "position": sched["position"],
            "missing_clock_dates": set(),
            "missing_clock_records": [],
            "missing_clock_count_extra": 0,
            "late_details": [],
            "early_leave_details": [],
            "absence_dates": set(),
            "absence_records": [],
            "mid_clock_issues": [],
            "daily_rate": daily_service_fee(sched["hourly_rate"], sched["daily_hours"],
                                             sched.get("monthly_total"), sched.get("actual_count"),
                                             sched.get("service_type")),
            "overtime_warnings": [],
        })

        if not all_clocks:
            entry["absence_dates"].add(work_date)
            entry["absence_records"].append({
                "date": work_date,
                "position": sched["position"],
                "shift_start": sched["shift_start"],
                "shift_end": sched["shift_end"],
                "clock_times": [],
            })
            continue

        if mid_clock_windows:
            mid_compliance = _check_mid_clock_compliance(
                all_clocks, mid_clock_windows, sched["shift_start"], sched["shift_end"], is_cross
            )
            if mid_compliance["mid_clock_issues"]:
                for issue in mid_compliance["mid_clock_issues"]:
                    entry["mid_clock_issues"].append({**issue, "date": work_date, "position": sched["position"], "shift_start": sched["shift_start"], "shift_end": sched["shift_end"], "clock_times": list(clock_display)})
                entry["missing_clock_count_extra"] += mid_compliance["total_missing_mid_clocks"]

        late, early = _calc_late_early_minutes(
            all_clocks, sched["shift_start"], sched["shift_end"], is_cross
        )
        _apply_late_early(entry, late, early, s04_sub, work_date, sched, clock_display, all_clocks)
        _check_missing_clockout(entry, is_cross, clocks, next_clocks, all_clocks, work_date, sched, clock_display)

    # 处理缺岗：签到表标记"缺岗"/"缺勤" = 确定缺勤，不比对考勤
    vacancy_absence_count = 0
    for (pos, slot_ident, work_date), vac in vacancies.items():
        vacancy_absence_count += 1
        # 假员工名带槽位标识：同名岗位的不同槽位缺岗各自成行，
        # 保证同一天同岗位多槽位缺勤按槽位数分别扣款（费率也各自取准）
        fake_name = f"[缺岗]{pos}({slot_ident})"
        entry = employee_data.setdefault(fake_name, {
            "employee_name": fake_name,
            "position": pos,
            "missing_clock_dates": set(),
            "missing_clock_records": [],
            "missing_clock_count_extra": 0,
            "late_details": [],
            "early_leave_details": [],
            "absence_dates": set(),
            "absence_records": [],
            "mid_clock_issues": [],
            "daily_rate": daily_service_fee(vac["hourly_rate"], vac["daily_hours"],
                                             vac.get("monthly_total"), vac.get("actual_count"),
                                             vac.get("service_type")),
            "overtime_warnings": [],
        })
        entry["absence_dates"].add(work_date)
        entry["absence_records"].append({
            "date": work_date,
            "position": pos,
            "shift_start": vac["shift_start"],
            "shift_end": vac["shift_end"],
            "clock_times": [],
        })
        entry["position"] = pos

    deduction_details = []
    for name, data in sorted(employee_data.items()):
        missing_clock_dates_sorted = sorted(data["missing_clock_dates"])
        missing_clock_records_sorted = sorted(data["missing_clock_records"], key=lambda r: r["date"])
        missing_clock_extra = data.get("missing_clock_count_extra", 0)
        missing_count = len(missing_clock_dates_sorted) + missing_clock_extra

        late_total = sum(d["amount"] for d in data["late_details"])
        early_total = sum(d["amount"] for d in data["early_leave_details"])

        absence_dates_list = sorted(data["absence_dates"])
        absence_records_sorted = sorted(data["absence_records"], key=lambda r: r["date"])
        absence_count = len(absence_dates_list)
        absence_amount = 0.0
        for _ in absence_dates_list:
            absence_amount += data["daily_rate"] * absence_multiplier

        missing_deduction = missing_count * missing_amount
        total = missing_deduction + late_total + early_total + round(absence_amount, 2)

        deduction_details.append({
            "employee_name": name,
            "position": data["position"],
            "missing_clock_count": missing_count,
            "missing_clock_free_limit": missing_free,
            "missing_clock_free_remaining": missing_free,
            "missing_clock_deductible": missing_count,
            "missing_clock_amount": missing_deduction,
            "missing_clock_dates": missing_clock_dates_sorted,
            "missing_clock_records": missing_clock_records_sorted,
            "missing_clock_extra": missing_clock_extra,
            "late_details": data["late_details"],
            "late_total": late_total,
            "early_leave_details": data["early_leave_details"],
            "early_leave_total": early_total,
            "mid_clock_issues": data["mid_clock_issues"],
            "absence_count": absence_count,
            "absence_dates": absence_dates_list,
            "absence_records": absence_records_sorted,
            "absence_daily_rate": data["daily_rate"],
            "absence_multiplier": absence_multiplier,
            "absence_amount": round(absence_amount, 2),
            "total_deduction": round(total, 2),
            "overtime_warnings": data.get("overtime_warnings", []),
        })

    total_missing = sum(d["missing_clock_amount"] for d in deduction_details)
    total_late = sum(d["late_total"] for d in deduction_details)
    total_early = sum(d["early_leave_total"] for d in deduction_details)
    total_absence = sum(d["absence_amount"] for d in deduction_details)
    total_overtime_warnings = sum(len(d.get("overtime_warnings", [])) for d in deduction_details)

    return {
        "deduction_details": deduction_details,
        "summary": {
            "total_missing_clock_amount": total_missing,
            "total_late_amount": total_late,
            "total_early_leave_amount": total_early,
            "total_absence_amount": round(total_absence, 2),
            "total_deduction": round(total_missing + total_late + total_early + total_absence, 2),
            "affected_employees": len(deduction_details),
            "overtime_warning_count": total_overtime_warnings,
        },
        "s04_rules": {
            "free_missing_clock_times": missing_free,
            "missing_clock_amount": missing_amount,
            "late_early_tiers": [
                {
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "amount": r.get("amount"),
                    "max_minutes": r.get("max_minutes"),
                }
                for r in sorted(
                    (r for r in s04_sub if _is_late_early_tier(r)),
                    key=lambda r: _as_positive_int(r.get("max_minutes")),
                )
            ],
            "absence_penalty_multiplier": absence_multiplier,
            "absence_penalty": f"日服务费×{absence_multiplier}",
        },
    }