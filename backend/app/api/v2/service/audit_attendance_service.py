"""S04 考勤管理扣款审核（人员级）。

签到表（Sheet3）单元格四态 → 审核分流：
- "缺岗"：确定缺勤，不比对考勤，直接记 S04-4 缺勤扣款
- 人名：人来了，比对 BI 考勤打卡，检查上下班卡与中间卡
- 休息/空：当天该岗无人，跳过
- 请假：有正当原因，不扣款

比对 BI 考勤后：
- S04-1 漏打卡：当月无打卡记录 / 迟到>60min / 早退>60min / 中间卡缺失，超出免扣次数后按 50 元/人次扣款
- S04-2 迟到/早退 ≤30 分钟：20 元/次
- S04-3 迟到/早退 ≤60 分钟（>30 且 ≤60）：50 元/次
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
    parse_shift_by_weekday,
    get_shift_for_date,
    parse_time_value,
    time_to_minutes,
    parse_mid_clock_time,
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
    try:
        return f"{audit_month}-{day:02d}"
    except Exception:
        return ""


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


# 缺勤/缺岗/脱岗扣款复用合同里的"缺编系数"（contract_deduction_coefficient）。
# 该系数同时作用于 S04-4 脱岗（日服务费 × N）和槽位缺编扣款。
def get_absence_coefficient(s04_rules: dict | None) -> float:
    """从合同规则里取缺编/脱岗扣款倍数（合同字段 contract_deduction_coefficient）。

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


def _build_schedule_index(position_infos: list[PositionInfo]) -> tuple[dict[tuple[str, str], dict], dict[tuple[str, str], dict]]:
    """构建 (姓名, 日期) → 排班信息 索引，以及 (岗位, 日期) → 缺岗信息 索引。

    关键逻辑：
    - 班次时间按周几分段解析（parse_shift_by_weekday），再根据每个日期的星期
      用 get_shift_for_date 选取当天对应班次。
    - "缺岗"单元格无论班次能否解析都收入 vacancies（签到表写缺岗=确定缺勤）。
    - 人名单元格同样不因班次解析失败而跳过（人来了就纳入比对）。
    """
    index: dict[tuple[str, str], dict] = {}
    vacancies: dict[tuple[str, str], dict] = {}
    for pi in position_infos:
        for p in pi.positions:
            shifts = parse_shift_by_weekday(p.shift_time)
            mid_clock_windows = parse_mid_clock_time(p.mid_clock_time)
            for slot in p.slots:
                for work_date, cells in slot.daily.items():
                    start, end = get_shift_for_date(shifts, work_date)
                    # 自动检测跨天：结束时间 <= 开始时间 → 跨天（夜班）
                    _s = time_to_minutes(parse_time_value(start))
                    _e = time_to_minutes(parse_time_value(end))
                    auto_cross = bool(_s is not None and _e is not None and _e <= _s)
                    for cell in cells:
                        status = cell.get("status", "")
                        if status == "缺岗":
                            key = (p.position_name, work_date)
                            if key not in vacancies:
                                vacancies[key] = {
                                    "shift_start": start,
                                    "shift_end": end,
                                    "position": p.position_name,
                                    "hourly_rate": p.hourly_rate,
                                    "daily_hours": p.daily_hours,
                                    "is_cross_midnight": auto_cross,
                                    "mid_clock_windows": mid_clock_windows,
                                }
                            continue
                        for name in cell.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                index[(nn, work_date)] = {
                                    "shift_start": start,
                                    "shift_end": end,
                                    "position": p.position_name,
                                    "hourly_rate": p.hourly_rate,
                                    "daily_hours": p.daily_hours,
                                    "is_cross_midnight": auto_cross,
                                    "mid_clock_windows": mid_clock_windows,
                                }
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

    clock_mins = []
    for t in clock_times:
        m = time_to_minutes(parse_time_value(t))
        if m is not None:
            if is_cross_midnight and m < start_min and m <= end_min + 120:
                m += 1440
            clock_mins.append(m)

    if not clock_mins:
        return 0, 0

    clock_mins.sort()
    actual_in = clock_mins[0]
    actual_out = clock_mins[-1]

    late = max(0, actual_in - start_min)
    if is_cross_midnight and end_min <= start_min:
        actual_out = actual_out % 1440 if actual_out > 1440 else actual_out
        early = max(0, end_min - actual_out)
    else:
        early = max(0, end_min - actual_out)

    return late, early


def _classify_late_early(minutes: int, s04_sub_rules: list[dict]) -> tuple[str, int]:
    if minutes <= 0:
        return "", 0
    if minutes > 60:
        return "S04-1", 0
    for sub in s04_sub_rules:
        if sub.get("code") == "S04-2" and minutes <= 30:
            return "S04-2", int(sub.get("amount", 20))
        if sub.get("code") == "S04-3" and minutes <= 60:
            return "S04-3", int(sub.get("amount", 50))
    return "S04-3", int(s04_sub_rules[-1].get("amount", 50)) if s04_sub_rules else 50


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

    clock_mins = []
    for t in clock_times:
        m = time_to_minutes(parse_time_value(t))
        if m is not None:
            if is_cross_midnight and m < start_min and m <= end_min + 120:
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

        # 计算该时间段内的打卡次数
        actual_count = 0
        for cm in clock_mins:
            cm_normalized = cm % 1440 if cm > 1440 else cm
            if ws_min <= cm_normalized <= we_min:
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
        s04_sub = s04_rules.get("sub_rules", [])
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
        # 构建 s04_sub 用于 _classify_late_early
        late_early_tiers = s04_rules.get("late_early_tiers", [])
        s04_sub = []
        for i, t in enumerate(late_early_tiers):
            code = "S04-2" if i == 0 else "S04-3"
            s04_sub.append({"code": code, "amount": t.get("amount", 20), "max_minutes": t.get("max_minutes", 30)})
        if s04_rules.get("late_early_over_minutes_as_absence"):
            s04_sub.append({"code": "S04-1", "amount": 0})
    else:
        missing_free = 3
        missing_amount = 50
        s04_4 = None
        s04_sub = []

    # 缺勤/脱岗扣款倍数：日服务费 × 缺编系数（合同字段 contract_deduction_coefficient）
    absence_multiplier = get_absence_coefficient(s04_rules)

    schedule_index, vacancies = _build_schedule_index(position_infos)
    bi_index = _build_bi_index(bi_records, month)

    employee_data: dict[str, dict] = {}

    for (name, work_date), sched in schedule_index.items():
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
            # 当日：>= 班次开始时间-2h缓冲（如 20:00-2h=18:00），排除前一个夜班的下班卡（07:xx、11:xx）
            # 次日：<= 班次结束时间+2h缓冲（如 08:00+2h=10:00），排除下一个班次的上班卡（19:xx）
            _s_min = time_to_minutes(parse_time_value(sched["shift_start"]))
            _e_min = time_to_minutes(parse_time_value(sched["shift_end"]))
            if _s_min is not None:
                _s_buf = max(0, _s_min - 120)
                clocks = [t for t in clocks
                          if (time_to_minutes(parse_time_value(t)) or -1) >= _s_buf]
            if _e_min is not None:
                _e_buf = _e_min + 120
                next_clocks = [t for t in next_clocks
                               if (time_to_minutes(parse_time_value(t)) or 9999) <= _e_buf]

        # 构建显示用打卡列表：
        # 当日打卡（上班卡+中间卡） → 次日打卡（中间卡+下班卡）
        # 当日不标日期，次日标日期前缀，各自按时间排序
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
            "daily_rate": round(sched["hourly_rate"] * sched["daily_hours"], 2),
        })

        if not all_clocks:
            # 签到表写了人名 = 人来了，但没有打卡记录 → 漏打卡
            entry["missing_clock_dates"].add(work_date)
            entry["missing_clock_records"].append({
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

        if late > 0:
            tier, amount = _classify_late_early(late, s04_sub)
            if tier == "S04-1":
                # 迟到>60min：人来了但严重迟到，按漏打卡处理（非缺勤）
                entry["missing_clock_dates"].add(work_date)
                if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
                    entry["missing_clock_records"].append({
                        "date": work_date,
                        "position": sched["position"],
                        "shift_start": sched["shift_start"],
                        "shift_end": sched["shift_end"],
                        "clock_times": list(clock_display),
                    })
            else:
                entry["late_details"].append({
                    "date": work_date,
                    "position": sched["position"],
                    "shift_start": sched["shift_start"],
                    "shift_end": sched["shift_end"],
                    "clock_in": all_clocks[0] if all_clocks else "",
                    "clock_times": list(clock_display),
                    "minutes": late,
                    "tier": tier,
                    "amount": amount,
                })

        if early > 0:
            tier, amount = _classify_late_early(early, s04_sub)
            if tier == "S04-1":
                entry["missing_clock_dates"].add(work_date)
                if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
                    entry["missing_clock_records"].append({
                        "date": work_date,
                        "position": sched["position"],
                        "shift_start": sched["shift_start"],
                        "shift_end": sched["shift_end"],
                        "clock_times": list(clock_display),
                    })
            else:
                entry["early_leave_details"].append({
                    "date": work_date,
                    "position": sched["position"],
                    "shift_start": sched["shift_start"],
                    "shift_end": sched["shift_end"],
                    "clock_out": all_clocks[-1] if all_clocks else "",
                    "clock_times": list(clock_display),
                    "minutes": early,
                    "tier": tier,
                    "amount": amount,
                })

        # 检查漏下班卡：有上班卡但无下班卡
        # 跨天班次：有当日打卡但无次日打卡 → 下班卡缺失
        # 非跨天班次：只有一条打卡 → 下班卡或上班卡缺失
        has_missing_clockout = False
        if is_cross:
            if clocks and not next_clocks:
                has_missing_clockout = True
        else:
            if len(all_clocks) == 1:
                has_missing_clockout = True

        if has_missing_clockout:
            entry["missing_clock_dates"].add(work_date)
            if not any(r["date"] == work_date for r in entry["missing_clock_records"]):
                entry["missing_clock_records"].append({
                    "date": work_date,
                    "position": sched["position"],
                    "shift_start": sched["shift_start"],
                    "shift_end": sched["shift_end"],
                    "clock_times": list(clock_display),
                })

    # 处理缺岗：签到表标记"缺岗" = 确定缺勤，不比对考勤
    vacancy_absence_count = 0
    for (pos, work_date), vac in vacancies.items():
        vacancy_absence_count += 1
        fake_name = f"[缺岗]{pos}"
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
            "daily_rate": round(vac["hourly_rate"] * vac["daily_hours"], 2) if vac["hourly_rate"] and vac["daily_hours"] else 0,
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
        })

    total_missing = sum(d["missing_clock_amount"] for d in deduction_details)
    total_late = sum(d["late_total"] for d in deduction_details)
    total_early = sum(d["early_leave_total"] for d in deduction_details)
    total_absence = sum(d["absence_amount"] for d in deduction_details)

    return {
        "deduction_details": deduction_details,
        "summary": {
            "total_missing_clock_amount": total_missing,
            "total_late_amount": total_late,
            "total_early_leave_amount": total_early,
            "total_absence_amount": round(total_absence, 2),
            "total_deduction": round(total_missing + total_late + total_early + total_absence, 2),
            "affected_employees": len(deduction_details),
        },
        "s04_rules": {
            "free_missing_clock_times": missing_free,
            "missing_clock_amount": missing_amount,
            "late_early_tiers": [
                {"code": r.get("code"), "name": r.get("name"), "amount": r.get("amount")}
                for r in s04_sub if r.get("code") in ("S04-2", "S04-3")
            ],
            "absence_penalty_multiplier": absence_multiplier,
            "absence_penalty": f"日服务费×{absence_multiplier}",
        },
    }