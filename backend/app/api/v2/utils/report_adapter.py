"""新流水线数据 → 旧版报告生成器所需的 results dict 适配层。

旧版 pdf_report_old.py（build_attendance_base_pdf /
build_combined_report_pdf）使用一套固定的 results 字段约定（见各函数体内的
results.get(...) 调用）。新流水线产出的 audit_results 数据结构不同，
本模块负责把新数据展平成旧字段，**只产出旧报告函数实际读取的字段**，
不增不减，保证报告样式和逻辑与旧版完全一致。
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any


def _detect_cross_midnight(start: str, end: str) -> bool:
    """根据班次时间自动检测是否跨天：结束 <= 开始 → 跨天。"""
    if not start or not end:
        return False
    def _to_min(t):
        m = re.match(r"(\d{1,2}):(\d{2})", str(t).strip())
        return int(m.group(1)) * 60 + int(m.group(2)) if m else None
    s, e = _to_min(start), _to_min(end)
    if s is None or e is None:
        return False
    return e <= s


def _next_date(iso_date: str) -> str:
    """计算 ISO 日期的下一天。"""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    except Exception:
        return ""


# ─────────────────────── 考勤明细 attendance_details ───────────────────────


def _normalize_employee_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _bi_day_to_iso(label, audit_month: str) -> str:
    text = str(label or "").strip()
    # 支持完整 ISO 日期标签（如 "2026-09-01"），用于跨月合并
    m_iso = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    day = int(digits[-2:]) if len(digits) >= 2 else int(digits)
    # audit_month 可能是 "202608" 或 "2026-08"，统一转成 "YYYY-MM" 前缀
    m_am = re.match(r"(\d{4})-?(\d{2})", str(audit_month or ""))
    if m_am:
        prefix = f"{m_am.group(1)}-{m_am.group(2)}"
    else:
        prefix = str(audit_month or "")
    return f"{prefix}-{day:02d}"


def _to_time(value) -> str:
    text = str(value or "").replace("：", ":").strip()
    match = re.search(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return text
    return f"{int(match.group(1))}:{match.group(2)}"


def _compute_actual_hours(clocks: list[str]) -> float:
    """按打卡时间粗略估算实际工时（首打卡~末打卡）。旧版用于统计实际出勤人。"""
    times = []
    for c in clocks or []:
        m = re.search(r"(\d{1,2}):(\d{2})", str(c))
        if m:
            times.append(int(m.group(1)) * 60 + int(m.group(2)))
    if len(times) >= 2:
        return round((max(times) - min(times)) / 60.0, 1)
    return 0.0


def _build_attendance_details(
    bi_records: list[dict],
    position_data: list[dict],
    audit_month: str,
    audit_results: dict | None,
) -> list[dict]:
    """把 bi_records + position_data 展平成旧版 attendance_details 列表。

    每条记录对应一个员工某一天，字段：
      employee_name / position / area / work_date / shift / schedule
      clock_in / clock_out / status / exception_reason
      shift_start_time / shift_end_time / actual_hours
      exception_type / deduction_amount / rule_name
    """
    # 1) 排班索引：(employee_name, date) -> shift_info
    schedule_idx: dict[tuple[str, str], dict] = {}
    for p in position_data or []:
        pos_name = p.get("position_name", "") or p.get("position", "")
        pos_shift_time = p.get("shift_time", "") or ""
        pos_cross_midnight = bool(p.get("is_cross_midnight", False))
        # 从 position 级别 shift_time 解析 start/end（slot 里通常没有这俩字段）
        pos_start = ""
        pos_end = ""
        if pos_shift_time:
            parts = re.split(r"[-~—至到]", pos_shift_time)
            if len(parts) == 2:
                pos_start = parts[0].strip()
                pos_end = parts[1].strip()
        for slot in p.get("slots", []) or []:
            area = slot.get("area", "")
            shift_name = slot.get("shift_name", "")
            shift_start = slot.get("shift_start", "") or pos_start
            shift_end = slot.get("shift_end", "") or pos_end
            for work_date, cells in (slot.get("daily") or {}).items():
                for cell in cells or []:
                    for name in cell.get("names", []) or []:
                        nn = _normalize_employee_name(name)
                        if not nn:
                            continue
                        schedule_idx[(nn, str(work_date))] = {
                            "position": pos_name,
                            "area": area,
                            "shift_name": shift_name or pos_shift_time,
                            "shift_start_time": shift_start,
                            "shift_end_time": shift_end,
                            "is_cross_midnight": pos_cross_midnight or _detect_cross_midnight(shift_start, shift_end),
                        }

    # 2) BI 打卡索引：(employee_name, date) -> [clocks]
    bi_idx: dict[tuple[str, str], list[str]] = {}
    emp_position: dict[str, str] = {}
    for rec in bi_records or []:
        name = _normalize_employee_name(rec.get("employee_name", ""))
        if not name:
            continue
        if rec.get("position"):
            emp_position.setdefault(name, rec.get("position", ""))
        att = rec.get("attendance", {}) or {}
        for day_label, clocks in att.items():
            iso = _bi_day_to_iso(day_label, audit_month)
            if not iso:
                continue
            cl = [_to_time(c) for c in (clocks or []) if c and str(c).strip()]
            if cl:
                bi_idx.setdefault((name, iso), []).extend(cl)

    # 3) 异常索引（从 audit_results.s04_attendance_audit.deduction_details）
    exception_idx: dict[tuple[str, str], list[dict]] = defaultdict(list)
    deduction_amount_map: dict[tuple[str, str], tuple[float, str]] = {}
    rule_name_map: dict[tuple[str, str], str] = {}
    s04 = (audit_results or {}).get("s04_attendance_audit", {}) or {}
    for detail in s04.get("deduction_details", []) or []:
        name = _normalize_employee_name(detail.get("employee_name", ""))
        if not name:
            continue
        for date_str in detail.get("missing_clock_dates", []) or []:
            exception_idx[(name, str(date_str))].append({"type": "漏打卡", "reason": "漏打卡"})
        for late in detail.get("late_details", []) or []:
            exception_idx[(name, str(late.get("date", "")))].append({
                "type": "迟到",
                "reason": f"迟到{int(late.get('minutes', 0) or 0)}分钟",
            })
        for early in detail.get("early_leave_details", []) or []:
            exception_idx[(name, str(early.get("date", "")))].append({
                "type": "早退",
                "reason": f"早退{int(early.get('minutes', 0) or 0)}分钟",
            })
        for date_str in detail.get("absence_dates", []) or []:
            exception_idx[(name, str(date_str))].append({"type": "缺勤", "reason": "缺岗(缺勤)"})
        for issue in detail.get("mid_clock_issues", []) or []:
            exception_idx[(name, str(issue.get("date", "")))].append({
                "type": "漏打卡",
                "reason": f"中间卡缺{issue.get('missing', 0)}次({issue.get('window', '')})",
            })
        # 该员工当天的总扣款映射到任意一天（旧版字段 deduction_amount 是一行一金额）
        # 简化处理：扣款总和落到第一个异常日期
        # 如果已确认，使用 final_total_deduction（确认后金额）
        final_total = detail.get("final_total_deduction")
        raw_total = detail.get("total_deduction", 0) or 0
        use_amount = float(final_total) if final_total is not None else float(raw_total)
        for dkey in list(exception_idx.keys()):
            if dkey[0] == name:
                deduction_amount_map[dkey] = (use_amount, detail.get("position", ""))
                rule_name_map[dkey] = "考勤扣款"
                break

    # 4) 合并产出 attendance_details
    #    只保留排班表中出现的员工，排除其他业务类型（如保安）的 BI 打卡
    details: list[dict] = []
    scheduled_names = {name for (name, _) in schedule_idx.keys()}
    all_keys = set(schedule_idx.keys())
    all_keys |= {k for k in bi_idx.keys() if k[0] in scheduled_names}
    all_keys |= set(exception_idx.keys())
    for (name, date_str) in sorted(all_keys, key=lambda x: (x[0], x[1])):
        sched = schedule_idx.get((name, date_str)) or {}
        # 当日打卡（上班卡+中间卡） → 次日打卡（中间卡+下班卡）
        # 当日不标日期，次日标日期前缀，各自按时间排序
        raw_clocks = list(bi_idx.get((name, date_str)) or [])
        raw_next_clocks: list[str] = []
        next_dt = ""
        if sched.get("is_cross_midnight"):
            next_dt = _next_date(date_str)
            if next_dt:
                raw_next_clocks = list(bi_idx.get((name, next_dt)) or [])

            # 跨天班次过滤：只保留属于当前班次的打卡
            # 当日：>= 班次开始时间-2h缓冲（如 20:00-2h=18:00），排除前一个夜班的下班卡（07:xx、11:xx）
            # 次日：<= 班次结束时间+2h缓冲（如 08:00+2h=10:00），排除下一个班次的上班卡（19:xx）
            def _to_min_val(t):
                m = re.match(r"(\d{1,2}):(\d{2})", str(t).strip())
                return int(m.group(1)) * 60 + int(m.group(2)) if m else None

            _s_min = _to_min_val(sched.get("shift_start_time", ""))
            _e_min = _to_min_val(sched.get("shift_end_time", ""))
            if _s_min is not None:
                _s_buf = max(0, _s_min - 120)
                raw_clocks = [t for t in raw_clocks
                              if (_to_min_val(t) or -1) >= _s_buf]
            if _e_min is not None:
                _e_buf = _e_min + 120
                raw_next_clocks = [t for t in raw_next_clocks
                                   if (_to_min_val(t) or 9999) <= _e_buf]

        def _sort_key(t: str) -> int:
            m = re.search(r"(\d{1,2}):(\d{2})", str(t))
            return int(m.group(1)) * 60 + int(m.group(2)) if m else 0

        clocks: list[str] = []
        if raw_clocks:
            clocks.extend(sorted(raw_clocks, key=_sort_key))
        if raw_next_clocks:
            clocks.extend([f"{next_dt} {t}" for t in sorted(raw_next_clocks, key=_sort_key)])
        exceptions = exception_idx.get((name, date_str)) or []
        exc_types = [e["type"] for e in exceptions]
        exc_reasons = [e["reason"] for e in exceptions]
        # 展示层兜底：排班了但完全没打卡且S04未检测到异常 → 标记为漏打卡
        if not exc_types and sched.get("shift_start_time") and not clocks:
            exc_types = ["漏打卡"]
            exc_reasons = ["排班但无打卡记录"]
        status = "正常" if not exc_types else "异常"
        exception_reason = "; ".join(exc_reasons) if exc_reasons else ""
        # 实际工时：按首末打卡时间估算，旧版用于统计实际出勤人
        actual_hours = _compute_actual_hours(clocks)
        amount, rule_position = deduction_amount_map.get((name, date_str), (0.0, ""))
        rule_name = rule_name_map.get((name, date_str), "")
        details.append({
            "employee_name": name,
            "position": sched.get("position") or emp_position.get(name, "") or rule_position,
            "area": sched.get("area", ""),
            "work_date": date_str,
            "shift": sched.get("shift_name", ""),
            "shift_name": sched.get("shift_name", ""),
            "shift_start_time": sched.get("shift_start_time", ""),
            "shift_end_time": sched.get("shift_end_time", ""),
            "schedule": (
                f"{sched.get('shift_start_time', '')}-{sched.get('shift_end_time', '')}"
                if sched.get("shift_start_time") and sched.get("shift_end_time")
                else sched.get("shift_name", "")
            ),
            "clock_in": clocks[0] if clocks else "",
            "clock_out": clocks[-1] if len(clocks) > 1 else "",
            "clock_times": clocks,
            "status": status,
            "exception_reason": exception_reason,
            "exception_type": "、".join(exc_types),
            "actual_hours": actual_hours,
            "deduction_amount": amount,
            "rule_name": rule_name,
        })
    return details


# ─────────────────────── 扣款明细 attendance_deductions ───────────────────────


def _build_attendance_deductions(
    audit_results: dict,
    attendance_details: list[dict],
) -> list[dict]:
    """把 s04.deduction_details + slot_details 转成旧版 attendance_deductions 列表。

    如果审核已确认（存在 confirmations），只输出被勾选确认的异常，
    且扣款金额根据确认状态计算（免扣款的行金额为0）。
    如果尚未确认，输出全部异常（回退到原始行为）。
    """
    rows: list[dict] = []
    s04 = audit_results.get("s04_attendance_audit", {}) or {}
    s04_rule_cfg = s04.get("s04_rules", {}) or {}
    # 如果审核已确认（存在 final_summary），只输出被勾选确认的异常；
    # 否则输出全部异常（回退到原始行为）。
    audit_finalized = bool(audit_results.get("final_summary"))

    for detail in s04.get("deduction_details", []) or []:
        name = detail.get("employee_name", "")
        position = detail.get("position", "")
        confirmations = detail.get("confirmations", {}) or {}

        def _is_confirmed(key: str) -> bool:
            """审核已确认时仅返回勾选确认的；未确认时全部包含。"""
            if not audit_finalized:
                return True
            conf = confirmations.get(key, {})
            return conf.get("confirmed", False)

        def _is_free(key: str) -> bool:
            if not audit_finalized:
                return False
            conf = confirmations.get(key, {})
            return conf.get("free_deduction", False)

        # ── 漏打卡 ──
        missing_dates = detail.get("missing_clock_dates", []) or []
        missing_amount = float(detail.get("missing_clock_amount", 0) or 0)
        missing_count = detail.get("missing_clock_count", 0) or len(missing_dates)
        per_amount = missing_amount / max(missing_count, 1) if missing_count > 0 and missing_amount > 0 else 0
        for date_str in missing_dates:
            key = f"missing|{name}|{date_str}"
            if not _is_confirmed(key):
                continue
            free = _is_free(key)
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "漏打卡",
                "deduction_rule": "漏打卡扣款",
                "deduction_amount": 0 if free else round(per_amount, 2),
                "calculation_detail": "漏打卡扣款" + ("（免扣款）" if free else ""),
                "rule_name": "漏打卡",
            })

        # ── 迟到 ──
        for late in detail.get("late_details", []) or []:
            date_str = late.get("date", "")
            key = f"late|{name}|{date_str}"
            if not _is_confirmed(key):
                continue
            free = _is_free(key)
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "迟到",
                "deduction_rule": "迟到扣款",
                "deduction_amount": 0 if free else late.get("amount", 0),
                "calculation_detail": f"迟到{int(late.get('minutes', 0) or 0)}分钟" + ("（免扣款）" if free else ""),
                "rule_name": "迟到",
            })

        # ── 早退 ──
        for early in detail.get("early_leave_details", []) or []:
            date_str = early.get("date", "")
            key = f"early|{name}|{date_str}"
            if not _is_confirmed(key):
                continue
            free = _is_free(key)
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "早退",
                "deduction_rule": "早退扣款",
                "deduction_amount": 0 if free else early.get("amount", 0),
                "calculation_detail": f"早退{int(early.get('minutes', 0) or 0)}分钟" + ("（免扣款）" if free else ""),
                "rule_name": "早退",
            })

        # ── 缺勤/缺岗 ──
        daily_rate = float(detail.get("absence_daily_rate", 0) or 0)
        absence_multiplier = float(
            detail.get("absence_multiplier")
            or s04_rule_cfg.get("absence_penalty_multiplier")
            or 1.0
        )
        for date_str in detail.get("absence_dates", []) or []:
            key = f"absence|{name}|{date_str}"
            if not _is_confirmed(key):
                continue
            free = _is_free(key)
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "缺岗",
                "deduction_rule": "缺勤扣款",
                "deduction_amount": 0 if free else round(daily_rate * absence_multiplier, 2),
                "calculation_detail": "缺勤扣款" + ("（免扣款）" if free else ""),
                "rule_name": "缺勤",
            })

        # ── 中间卡缺失 ──
        for issue in detail.get("mid_clock_issues", []) or []:
            date_str = issue.get("date", "")
            window = issue.get("window", "")
            key = f"mid|{name}|{date_str}|{window}"
            if not _is_confirmed(key):
                continue
            free = _is_free(key)
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "漏打卡",
                "deduction_rule": "中间卡缺失",
                "deduction_amount": 0 if free else (issue.get("missing", 0) or 0) * 50,
                "calculation_detail": f"中间卡缺{issue.get('missing', 0)}次({window})" + ("（免扣款）" if free else ""),
                "rule_name": "漏打卡",
            })

    # 岗位缺编扣款（slot_details）— 仅在未确认时展示，确认后不计入扣款
    if not audit_finalized:
        for slot in audit_results.get("slot_details", []) or []:
            if (slot.get("shortage_amount") or 0) <= 0:
                continue
            rows.append({
                "employee_name": "",
                "position": slot.get("position", ""),
                "work_date": "",
                "exception_type": "岗位缺编",
                "deduction_rule": "岗位缺编扣款",
                "deduction_amount": slot.get("shortage_amount", 0),
                "calculation_detail": f"缺岗{slot.get('shortage_days', 0)}天 × 日服务费",
                "rule_name": "岗位缺编",
            })
    return rows


# ─────────────────────── 人员扣款汇总 deduction_summary ───────────────────────


def _build_deduction_summary(audit_results: dict, attendance_deductions: list[dict]) -> list[dict]:
    """按员工聚合扣款，返回旧版 deduction_summary 列表（TABLE_COLUMNS 期望
    employee_name / position / exception_count / total_deduction）。

    如果审核已确认（存在 final_total_deduction），使用确认后的金额；
    否则回退到从 attendance_deductions 行汇总。
    """
    # 构建员工 → final_total_deduction 映射
    final_map: dict[str, float] = {}
    s04 = audit_results.get("s04_attendance_audit", {}) or {}
    for detail in s04.get("deduction_details", []) or []:
        name = detail.get("employee_name", "")
        if name and "final_total_deduction" in detail:
            final_map[name] = float(detail.get("final_total_deduction", 0) or 0)

    by_emp: dict[str, dict] = defaultdict(lambda: {"attendance_deduction": 0.0, "position_deduction": 0.0, "total_deduction": 0.0, "exception_count": 0, "position": ""})
    for d in attendance_deductions:
        name = d.get("employee_name") or ""
        if not name:
            continue
        amt = float(d.get("deduction_amount", 0) or 0)
        if d.get("exception_type") == "岗位缺编":
            by_emp[name]["position_deduction"] += amt
        else:
            by_emp[name]["attendance_deduction"] += amt
            by_emp[name]["exception_count"] += 1
        by_emp[name]["total_deduction"] += amt
        by_emp[name]["position"] = by_emp[name]["position"] or d.get("position", "")

    # 如果有确认后的金额，用它覆盖 attendance_deduction 和 total_deduction
    for name, final_amt in final_map.items():
        if name in by_emp:
            by_emp[name]["attendance_deduction"] = final_amt
            by_emp[name]["total_deduction"] = final_amt + by_emp[name]["position_deduction"]

    rows = [
        {
            "employee_name": n,
            "position": v["position"],
            "exception_count": v["exception_count"],
            "total_deduction": round(v["total_deduction"], 2),
        }
        for n, v in by_emp.items()
    ]
    rows.sort(key=lambda r: r["total_deduction"], reverse=True)
    return rows


def _build_deduction_total_summary(summary: dict) -> list[dict]:
    """生成『人员扣款汇总』的总额 dict（build_management_suggestions 读取
    deduction_summary[0].total_deduction_amount 用）。"""
    attendance_total = float(summary.get("attendance_deduction_amount", 0) or 0)
    position_total = float(summary.get("position_deduction_amount", 0) or 0)
    return [{
        "attendance_deduction_amount": round(attendance_total, 2),
        "position_deduction_amount": round(position_total, 2),
        "total_deduction_amount": round(attendance_total + position_total, 2),
    }]


# ─────────────────────── 异常统计 exception_statistics ───────────────────────


def _build_exception_statistics(attendance_deductions: list[dict]) -> list[dict]:
    """按 (员工, 异常类型) 聚合异常次数，用于 build_copyable_summary。"""
    counter: dict[tuple[str, str], int] = defaultdict(int)
    pos_map: dict[str, str] = {}
    for d in attendance_deductions:
        name = d.get("employee_name") or ""
        if not name or d.get("exception_type") == "岗位缺编":
            continue
        counter[(name, d.get("exception_type", "") or "其他")] += 1
        pos_map[name] = pos_map.get(name) or d.get("position", "")
    rows = [
        {"employee_name": n, "position": pos_map.get(n, ""), "exception_type": t, "exception_count": c}
        for (n, t), c in counter.items()
    ]
    rows.sort(key=lambda r: r["exception_count"], reverse=True)
    return rows


# ─────────────────────── 排班审核 position_fulfillment ───────────────────────


def _build_position_fulfillment(audit_results: dict) -> list[dict]:
    """把 slot_summary 转成旧版 position_fulfillment 列表。"""
    rows: list[dict] = []
    for s in audit_results.get("summary", []) or []:
        rows.append({
            "position": s.get("position", ""),
            "area": s.get("area", ""),
            "scheduled_headcount": s.get("required_days", 0),
            "actual_attendance_count": s.get("normal_days", 0),
            "result_status": "正常" if (s.get("shortage_days") or 0) == 0 and (s.get("pending_days") or 0) == 0 else "异常",
            "calculation_detail": (
                f"应出勤{s.get('required_days', 0)}, 正常{s.get('normal_days', 0)}, "
                f"缺岗{s.get('shortage_days', 0)}, 待复核{s.get('pending_days', 0)}, "
                f"扣款{s.get('shortage_amount', 0)}元"
            ),
        })
    return rows


# ─────────────────────── 总 summary 字典 ───────────────────────


def _build_summary_dict(audit_results: dict, audit_month: str, attendance_deductions: list[dict] | None = None) -> dict:
    s04 = audit_results.get("s04_attendance_audit", {}) or {}
    s04_sum = s04.get("summary", {}) or {}
    final_sum = audit_results.get("final_summary", {}) or {}
    slot_summary = audit_results.get("summary", []) or []
    slot_details_raw = audit_results.get("slot_details", []) or []
    schedule_task_count = sum(1 for d in slot_details_raw if d.get("status") not in ("休息", "请假"))
    audited_days = _month_days_from_str(audit_month)
    # 第一次异常数 = s04.deduction_details 中的总记录数（含岗位缺编）
    first_exception_count = len(s04.get("deduction_details", []) or [])
    # 确认后异常人数
    confirmed_employees = int(final_sum.get("affected_employees") or s04_sum.get("affected_employees", 0) or 0)
    # 已确认异常条数（attendance_deductions 中的行数）
    confirmed_count = sum(1 for d in (attendance_deductions or []))
    # 异常率
    if schedule_task_count > 0:
        first_exception_rate = round(first_exception_count / schedule_task_count * 100, 1)
        confirmed_exception_rate = round(confirmed_employees / schedule_task_count * 100, 1)
    else:
        first_exception_rate = 0.0
        confirmed_exception_rate = 0.0
    # 岗位扣款
    position_deduction = sum(
        float(d.get("deduction_amount", 0) or 0)
        for d in (attendance_deductions or [])
        if d.get("exception_type") == "岗位缺编"
    )
    if not position_deduction:
        position_deduction = sum(float(s.get("shortage_amount", 0) or 0) for s in slot_summary)
    # 人员考勤扣款：如果审核已确认，使用 final_summary 中的确认金额；
    # 否则回退到从 attendance_deductions 行汇总。
    if final_sum and "total_deduction" in final_sum:
        attendance_deduction = float(final_sum.get("total_deduction", 0) or 0)
        # 已确认审核：总扣款 = 考勤扣款（不含岗位缺编）
        position_deduction = 0.0
        total_deduction = round(attendance_deduction, 2)
    else:
        attendance_deduction = sum(
            float(d.get("deduction_amount", 0) or 0)
            for d in (attendance_deductions or [])
            if d.get("exception_type") != "岗位缺编"
        )
        total_deduction = round(attendance_deduction + position_deduction, 2)
    return {
        "schedule_task_count": schedule_task_count,
        "exception_count": first_exception_count,
        "first_exception_rate": first_exception_rate,
        "confirmed_exception_count": confirmed_employees,
        "confirmed_exception_rate": confirmed_exception_rate,
        "confirmed_count": confirmed_count,
        "skipped_count": max(first_exception_count - confirmed_count, 0),
        "total_deduction": total_deduction,
        "attendance_deduction_amount": round(attendance_deduction, 2),
        "position_deduction_amount": round(position_deduction, 2),
        "audited_days": audited_days,
        "position_count": len({s.get("position", "") for s in slot_summary if s.get("position")}),
    }


def _month_days_from_str(audit_month: str) -> int:
    from datetime import datetime
    m = re.search(r"(\d{4})[-年/]?(\d{1,2})", str(audit_month or ""))
    if not m:
        return 0
    year, month = int(m.group(1)), int(m.group(2))
    if month == 12:
        next_month = datetime(year + 1, 1, 1)
    else:
        next_month = datetime(year, month + 1, 1)
    return (next_month - datetime(year, month, 1)).days


# ─────────────────────── 顶层：adapt_to_old_results ───────────────────────


def adapt_to_old_results(
    *,
    project_name: str,
    business_type: str,
    audit_month: str,
    bi_records: list[dict] | None = None,
    position_data: list[dict] | None = None,
    audit_results: dict | None = None,
    contract: dict | None = None,
    kind: str = "attendance",
) -> dict:
    """把新流水线数据转成旧版报告函数消费的 results dict。

    返回的 dict 字段集是旧版 pdf_report_old 各函数体内 results.get(...) 调用的并集，
    不增不减，确保报告样式和逻辑与旧版完全一致。

    kind 决定扣款汇总两块数据的形态：
      - "combined"（审核汇总 build_combined_report_pdf）：deduction_summary 必须是
        单条总额 dict（build_management_suggestions 读 total_deduction_amount），
        而 per-employee 列表放到 employee_deduction_summary 里，避免重复渲染。
      - "attendance"（考勤明细）不渲染扣款汇总，两种皆可。
    """
    bi_records = bi_records or []
    position_data = position_data or []
    audit_results = audit_results or {}

    attendance_details = _build_attendance_details(bi_records, position_data, audit_month, audit_results)
    attendance_deductions = _build_attendance_deductions(audit_results, attendance_details)
    deduction_summary_per_emp = _build_deduction_summary(audit_results, attendance_deductions)
    exception_statistics = _build_exception_statistics(attendance_deductions)
    position_fulfillment = _build_position_fulfillment(audit_results)
    summary = _build_summary_dict(audit_results, audit_month, attendance_deductions)

    # 异常率
    if summary["schedule_task_count"]:
        summary["first_exception_rate"] = round(
            summary["exception_count"] / summary["schedule_task_count"] * 100, 1
        )
        summary["confirmed_exception_rate"] = round(
            summary["confirmed_exception_count"] / summary["schedule_task_count"] * 100, 1
        )

    # 按报告类型决定扣款汇总的两种数据形态
    if kind == "combined":
        deduction_summary = _build_deduction_total_summary(summary)
        employee_deduction_summary = deduction_summary_per_emp
    else:
        deduction_summary = deduction_summary_per_emp
        employee_deduction_summary = []

    contract = contract or {}
    return {
        # 项目基本信息
        "project_info": {
            "项目名称": project_name,
            "审核月份": audit_month,
            "合同编号": contract.get("contract_no", ""),
            "供应商": contract.get("supplier", ""),
        },
        "active_contract": {"contract_name": contract.get("contract_name", "未匹配")},
        "audit_business_types": [business_type] if business_type else [],
        # 总览汇总
        "summary": summary,
        # 排班履约
        "position_fulfillment": position_fulfillment,
        # 考勤明细（旧版必读）
        "attendance_details": attendance_details,
        # 扣款明细 + 人员汇总
        "attendance_deductions": attendance_deductions,
        "deduction_summary": deduction_summary,
        "employee_deduction_summary": employee_deduction_summary,
        # 异常统计（用于 build_copyable_summary）
        "exception_statistics": exception_statistics,
    }
