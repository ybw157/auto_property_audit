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
from typing import Any


# ─────────────────────── 考勤明细 attendance_details ───────────────────────


def _normalize_employee_name(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _bi_day_to_iso(label, audit_month: str) -> str:
    text = str(label or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    day = int(digits[-2:]) if len(digits) >= 2 else int(digits)
    try:
        return f"{audit_month}-{day:02d}"
    except Exception:
        return ""


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
        for slot in p.get("slots", []) or []:
            area = slot.get("area", "")
            shift_name = slot.get("shift_name", "")
            shift_start = slot.get("shift_start", "")
            shift_end = slot.get("shift_end", "")
            for work_date, cells in (slot.get("daily") or {}).items():
                for cell in cells or []:
                    for name in cell.get("names", []) or []:
                        nn = _normalize_employee_name(name)
                        if not nn:
                            continue
                        schedule_idx[(nn, str(work_date))] = {
                            "position": pos_name,
                            "area": area,
                            "shift_name": shift_name,
                            "shift_start_time": shift_start,
                            "shift_end_time": shift_end,
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
            exception_idx[(name, str(date_str))].append({"type": "缺勤", "reason": "脱岗(缺勤)"})
        for issue in detail.get("mid_clock_issues", []) or []:
            exception_idx[(name, str(issue.get("date", "")))].append({
                "type": "漏打卡",
                "reason": f"中间卡缺{issue.get('missing', 0)}次({issue.get('window', '')})",
            })
        # 该员工当天的总扣款映射到任意一天（旧版字段 deduction_amount 是一行一金额）
        # 简化处理：扣款总和落到第一个异常日期
        for dkey in list(exception_idx.keys()):
            if dkey[0] == name:
                deduction_amount_map[dkey] = (
                    float(detail.get("total_deduction", 0) or 0),
                    detail.get("position", ""),
                )
                rule_name_map[dkey] = "考勤扣款"
                break

    # 4) 合并产出 attendance_details
    details: list[dict] = []
    all_keys = set(schedule_idx.keys()) | set(bi_idx.keys()) | set(exception_idx.keys())
    for (name, date_str) in sorted(all_keys, key=lambda x: (x[0], x[1])):
        sched = schedule_idx.get((name, date_str)) or {}
        clocks = bi_idx.get((name, date_str)) or []
        exceptions = exception_idx.get((name, date_str)) or []
        exc_types = [e["type"] for e in exceptions]
        exc_reasons = [e["reason"] for e in exceptions]
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
    """把 s04.deduction_details + slot_details 转成旧版 attendance_deductions 列表。"""
    rows: list[dict] = []
    s04 = audit_results.get("s04_attendance_audit", {}) or {}
    for detail in s04.get("deduction_details", []) or []:
        name = detail.get("employee_name", "")
        position = detail.get("position", "")
        # 各种异常类型生成多条扣款明细
        for date_str in detail.get("missing_clock_dates", []) or []:
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "漏打卡",
                "deduction_rule": "漏打卡扣款",
                "deduction_amount": round(float(detail.get("missing_clock_amount", 0) or 0) / max(len(detail.get("missing_clock_dates", []) or []), 1), 2),
                "calculation_detail": "漏打卡扣款",
                "rule_name": "漏打卡",
            })
        for late in detail.get("late_details", []) or []:
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": late.get("date", ""),
                "exception_type": "迟到",
                "deduction_rule": "迟到扣款",
                "deduction_amount": late.get("amount", 0),
                "calculation_detail": f"迟到{int(late.get('minutes', 0) or 0)}分钟",
                "rule_name": "迟到",
            })
        for early in detail.get("early_leave_details", []) or []:
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": early.get("date", ""),
                "exception_type": "早退",
                "deduction_rule": "早退扣款",
                "deduction_amount": early.get("amount", 0),
                "calculation_detail": f"早退{int(early.get('minutes', 0) or 0)}分钟",
                "rule_name": "早退",
            })
        for date_str in detail.get("absence_dates", []) or []:
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": date_str,
                "exception_type": "脱岗",
                "deduction_rule": "缺勤扣款",
                "deduction_amount": round(float(detail.get("absence_amount", 0) or 0) / max(len(detail.get("absence_dates", []) or []), 1), 2),
                "calculation_detail": "缺勤扣款",
                "rule_name": "缺勤",
            })
        for issue in detail.get("mid_clock_issues", []) or []:
            rows.append({
                "employee_name": name,
                "position": position,
                "work_date": issue.get("date", ""),
                "exception_type": "漏打卡",
                "deduction_rule": "中间卡缺失",
                "deduction_amount": 0,
                "calculation_detail": f"中间卡缺{issue.get('missing', 0)}次({issue.get('window', '')})",
                "rule_name": "漏打卡",
            })

    # 岗位缺编扣款（slot_details）
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
    employee_name / position / exception_count / total_deduction）。"""
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
    schedule_task_count = sum(int(s.get("required_days", 0) or 0) for s in slot_summary)
    audited_days = _month_days_from_str(audit_month)
    # 异常条数 = 非"岗位缺编"的扣款明细行数（漏打卡/迟到/早退/脱岗/中间卡）
    exception_count = sum(1 for d in (attendance_deductions or []) if d.get("exception_type") != "岗位缺编")
    # 考勤扣款 = 扣款明细中个人考勤部分（迟到/早退/漏打卡/缺勤/中间卡）之和，
    # 与『扣款明细』表中实际展示的个人考勤行口径一致。
    attendance_deduction = sum(
        float(d.get("deduction_amount", 0) or 0)
        for d in (attendance_deductions or [])
        if d.get("exception_type") != "岗位缺编"
    )
    # 岗位扣款 = 岗位缺编扣款之和（与『扣款明细』表中"岗位缺编"行口径一致）
    position_deduction = sum(
        float(d.get("deduction_amount", 0) or 0)
        for d in (attendance_deductions or [])
        if d.get("exception_type") == "岗位缺编"
    )
    if not position_deduction:
        position_deduction = sum(float(s.get("shortage_amount", 0) or 0) for s in slot_summary)
    # 总扣款 = 考勤扣款 + 岗位扣款，与报告"总扣款金额 = 考勤扣款 + 岗位扣款"显示口径一致。
    total_deduction = round(attendance_deduction + position_deduction, 2)
    confirmed_employees = int(final_sum.get("affected_employees") or s04_sum.get("affected_employees", 0) or 0)
    return {
        "schedule_task_count": schedule_task_count,
        "exception_count": exception_count,
        "first_exception_rate": 0.0,
        "confirmed_exception_count": confirmed_employees,
        "confirmed_exception_rate": 0.0,
        "confirmed_count": confirmed_employees,
        "skipped_count": 0,
        "total_deduction": total_deduction,
        "attendance_deduction_amount": round(attendance_deduction, 2),
        "position_deduction_amount": round(position_deduction, 2),
        "audited_days": audited_days,
        "position_count": len({s.get("position", "") for s in slot_summary if s.get("position")}),
    }


def _month_days_from_str(audit_month: str) -> int:
    from datetime import datetime
    m = re.search(r"(\d{4})[-年/](\d{1,2})", str(audit_month or ""))
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
