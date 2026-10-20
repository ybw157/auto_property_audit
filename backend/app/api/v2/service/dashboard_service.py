"""集团管理员驾驶舱聚合统计。

数据来源：AuditResult（审核结果）、PositionInfo（排班上传）、User（项目账号口径）。
所有统计均基于已落库数据，不做实时审核；audit_month 缺省取最近一个有审核数据的月份。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import func

from app.api.v2.core.database import get_db
from app.api.v2.models.audit_result_models import AuditResult
from app.api.v2.models.position_models import PositionInfo
from app.api.v2.models.user import User
from app.api.v2.service.audit_result_service import audit_totals_metrics

# 异常率预警阈值（%）：超过该值的项目进「风险提示」并在驾驶舱计为超标项目
EXCEPTION_RATE_THRESHOLD = 10.0

# 扣款归因：异常类型 → s04_attendance_audit.summary 里的金额字段。
# 用 summary 而非员工级 final_*_amount，后者仅在 status=已确认 的记录中存在。
DEDUCTION_TYPE_KEYS = {
    "缺勤": "total_absence_amount",
    "漏打卡": "total_missing_clock_amount",
    "早退": "total_early_leave_amount",
    "迟到": "total_late_amount",
}
# 不直接产生扣款、只作预警提示的项
WARNING_TYPE_KEYS = {
    "中间卡异常": "mid_clock_issue_count",
    "加班预警": "overtime_warning_count",
}


def _current_month() -> str:
    return datetime.now().strftime("%Y%m")


def _parse_results_json(raw: Any) -> dict:
    """results_json 落库为单 dict 的 JSON 串，兼容 list/None 兜底。

    注意：MySQL JSON 列在部分写入路径下存的是「JSON 字符串」（二次编码），
    直接当 dict/list 用会静默降级为空 dict，导致驾驶舱所有指标恒为 0，
    因此这里先做一次字符串反序列化。
    """
    if not raw:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return raw[0] if raw else {}
    return {}


def _count_exception_types(data: dict) -> dict[str, int]:
    """从单条审核结果解析异常类型分布。

    deduction_details 每个员工含 missing_clock_dates / mid_clock_issues /
    late_details / early_leave_details / absence_dates 五类条目，按类型计次。
    """
    counter = {"漏打卡": 0, "中间卡异常": 0, "迟到": 0, "早退": 0, "缺勤": 0}
    s04 = data.get("s04_attendance_audit", {}) or {}
    for detail in s04.get("deduction_details", []) or []:
        counter["漏打卡"] += len(detail.get("missing_clock_dates", []) or [])
        counter["中间卡异常"] += len(detail.get("mid_clock_issues", []) or [])
        counter["迟到"] += len(detail.get("late_details", []) or [])
        counter["早退"] += len(detail.get("early_leave_details", []) or [])
        counter["缺勤"] += len(detail.get("absence_dates", []) or [])
    return counter


def _available_months(db) -> list[str]:
    """可切换的月份：审核结果表 + 排班编制表中出现过的月份（YYYYMM），倒序。

    额外补上当前自然月，便于查看当月实时进度（当月可能还没有任何数据）。
    """
    months: set[str] = set()
    try:
        for r in db.query(AuditResult.audit_month).distinct().all():
            if r[0]:
                months.add(r[0])
    except Exception:
        pass
    try:
        for r in db.query(PositionInfo.audit_month).distinct().all():
            if r[0]:
                months.add(r[0])
    except Exception:
        pass
    months.add(_current_month())
    return sorted(months, reverse=True)


def _latest_month_with_data(db) -> str:
    """返回默认展示的月份（YYYYMM）。

    优先取最近一个「已有审核结果」的月份，保证打开就有数；
    仅当库里一条审核记录都没有时，才退回最近一个有排班的月份。
    """
    try:
        row = (
            db.query(AuditResult.audit_month)
            .filter(AuditResult.audit_month != "")
            .order_by(AuditResult.audit_month.desc())
            .first()
        )
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    try:
        prow = (
            db.query(PositionInfo.audit_month)
            .filter(PositionInfo.audit_month != "")
            .order_by(PositionInfo.audit_month.desc())
            .first()
        )
        if prow and prow[0]:
            return prow[0]
    except Exception:
        pass
    return ""


def _prev_month(month: str) -> str:
    """返回上一个自然月（YYYYMM），跨年自动回退。"""
    try:
        y, m = int(month[:4]), int(month[4:6])
    except Exception:
        return ""
    m -= 1
    if m == 0:
        y, m = y - 1, 12
    return f"{y}{m:02d}"


def _month_metrics(month: str) -> tuple[float, float]:
    """单个自然月的（扣款总额, 平均异常率），用于环比。"""
    db = next(get_db())
    try:
        rows = db.query(AuditResult).filter(AuditResult.audit_month == month).all()
    finally:
        db.close()
    ded = 0.0
    exc = 0
    sch = 0
    for r in rows:
        data = _parse_results_json(r.results_json)
        mt = audit_totals_metrics(data)
        ded += float(mt.get("total_deduction", 0) or 0)
        exc += int(mt.get("confirmed_count", 0) or 0)
        sch += sum(
            1 for d in (data.get("slot_details") or [])
            if d.get("status") not in ("休息", "请假")
        )
    rate = round(exc / sch * 100, 1) if sch > 0 else 0
    return round(ded, 2), rate


def _last_n_months(n: int) -> list[str]:
    now = datetime.now()
    months: list[str] = []
    for i in range(n - 1, -1, -1):
        y, m = divmod(now.year * 12 + (now.month - 1) - i, 12)
        months.append(f"{y}{m + 1:02d}")
    return months


def group_summary(audit_month: str = "") -> dict:
    """集团驾驶舱汇总数据。

    返回结构：
    - kpi: 项目总数 / 已审核 / 待审核 / 扣款总额 / 平均异常率 / 完成率
    - project_usage: 各项目使用情况明细
    - exception_type_distribution: 异常类型分布（饼图）
    - monthly_trend: 近 6 个月异常率与扣款趋势（折线/柱状）
    - risk_projects: 异常率 > 5% 或当月未审核的项目（风险提示卡）
    """
    db = next(get_db())
    try:
        # 未指定月份时，取最近一个已有审核数据的月份，避免月初打开是空面板
        month = audit_month or _latest_month_with_data(db) or _current_month()
        available_months = _available_months(db)
        # 项目总数的口径：用户表中「非管理员账号」所绑定的项目（去重）
        account_projects = [
            (r[0] or "").strip()
            for r in db.query(User.project_name)
            .filter(User.role.is_(False))
            .filter(User.status == "active")
            .distinct()
            .all()
        ]
    finally:
        db.close()

    db = next(get_db())
    try:
        audits = (
            db.query(AuditResult)
            .filter(AuditResult.audit_month == month)
            .all()
        )
        positions = (
            db.query(PositionInfo)
            .filter(PositionInfo.audit_month == month)
            .all()
        )
    finally:
        db.close()

    # 项目总数以用户表中的非管理员账号为准；排班/审核表只用于填充各项目的
    # 审核明细，不再参与「项目总数」计数，避免口径随数据量漂移。
    # （合同表已不参与任何统计，不再查询，省掉一次全表扫描）
    all_projects: set[str] = {p for p in account_projects if p}
    # 有数据但尚未开账号的项目也补进来，保证明细行不丢（如历史遗留项目）
    for r in audits:
        all_projects.add(r.project_name)
    for p in positions:
        all_projects.add(p.project_name)
    all_projects.discard("")

    audited_projects: set[str] = set()          # 有审核记录（已审核 + 已确认）
    confirmed_projects: set[str] = set()        # status 全部为「已确认」，项目闭环
    pending_confirm_projects: set[str] = set()  # 仍有「已审核」未确认的记录
    project_status_map: dict[str, set[str]] = defaultdict(set)
    pending_projects: set[str] = set()
    total_deduction = 0.0
    weighted_exceptions = 0.0
    weighted_schedule = 0
    type_counter: dict[str, int] = defaultdict(int)
    # 各异常类型的扣款金额（取自 s04.summary，比员工级 final_* 字段覆盖面更全：
    # 后者只在「已确认」记录里存在）
    type_amount: dict[str, float] = {label: 0.0 for label in DEDUCTION_TYPE_KEYS}
    affected_employees = 0
    overtime_warnings = 0
    # 供应商 → 扣款聚合（供应商取自排班表，(项目,业态,服务类型) 定位）
    supplier_stats: dict[str, dict] = defaultdict(
        lambda: {"deduction": 0.0, "projects": set()}
    )
    pos_index = {
        (p.project_name, p.business_type, p.service_type): p.supplier
        for p in positions
    }
    per_project: dict[str, dict] = defaultdict(lambda: {
        "deduction": 0.0,
        "exception_count": 0,
        "schedule_count": 0,
        "audit_status": "待审核",
        "business_types": set(),
        "service_types": set(),
        "last_audit_at": "",
    })

    for r in audits:
        proj = r.project_name
        audited_projects.add(proj)
        project_status_map[proj].add(r.status)
        data = _parse_results_json(r.results_json)
        metrics = audit_totals_metrics(data)
        total_deduction += float(metrics.get("total_deduction", 0) or 0)
        weighted_exceptions += (
            float(metrics.get("confirmed_count", 0) or 0)
        )
        weighted_schedule += int(
            sum(1 for d in (data.get("slot_details") or [])
                if d.get("status") not in ("休息", "请假"))
        ) or 0
        for k, v in _count_exception_types(data).items():
            type_counter[k] += v

        # 扣款归因：按类型累加金额，并统计涉及人数与加班预警
        s04_summary = (data.get("s04_attendance_audit", {}) or {}).get("summary") or {}
        for label, sum_key in DEDUCTION_TYPE_KEYS.items():
            type_amount[label] += float(s04_summary.get(sum_key) or 0)
        affected_employees += int(s04_summary.get("affected_employees") or 0)
        overtime_warnings += int(s04_summary.get("overtime_warning_count") or 0)

        # 供应商归因：供应商来自排班表，按 (项目, 业态, 服务类型) 定位
        supplier = (pos_index.get((r.project_name, r.business_type, r.service_type)) or "").strip()
        sup_rec = supplier_stats[supplier or "未标注供应商"]
        sup_rec["deduction"] += float(metrics.get("total_deduction", 0) or 0)
        sup_rec["projects"].add(r.project_name)

        slot_count = sum(
            1 for d in (data.get("slot_details") or [])
            if d.get("status") not in ("休息", "请假")
        )
        rec = per_project[proj]
        rec["deduction"] += float(metrics.get("total_deduction", 0) or 0)
        rec["exception_count"] += int(metrics.get("confirmed_count", 0) or 0)
        rec["schedule_count"] += slot_count
        rec["business_types"].add(r.business_type)
        rec["service_types"].add(r.service_type)
        # 明细里给领导看的三档：已确认 / 待确认（AI 审完等确认）/ 待审核（未开始）
        if r.status == "已审核":
            rec["audit_status"] = "待确认"
        elif r.status == "已确认" and rec["audit_status"] != "待确认":
            rec["audit_status"] = "已确认"
        ts = r.confirmed_at or (r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else "")
        if ts > rec["last_audit_at"]:
            rec["last_audit_at"] = ts

    # 项目整体闭环状态：一条记录「已审核」未确认，整个项目算「待确认」；
    # 只有全部记录都是「已确认」才算项目已完成。
    for proj, statuses in project_status_map.items():
        if "已审核" in statuses:
            pending_confirm_projects.add(proj)
        elif statuses and statuses <= {"已确认"}:
            confirmed_projects.add(proj)

    for proj in all_projects:
        if proj not in audited_projects:
            pending_projects.add(proj)

    project_usage: list[dict] = []
    for proj in sorted(all_projects):
        rec = per_project.get(proj, {
            "deduction": 0.0,
            "exception_count": 0,
            "schedule_count": 0,
            "audit_status": "待审核",
            "business_types": set(),
            "service_types": set(),
            "last_audit_at": "",
        })
        rate = (
            round(rec["exception_count"] / rec["schedule_count"] * 100, 1)
            if rec["schedule_count"] > 0 else 0
        )
        project_usage.append({
            "project_name": proj,
            "business_types": "、".join(sorted(rec["business_types"])) or "-",
            "service_types": "、".join(sorted(rec["service_types"])) or "-",
            "audit_status": rec["audit_status"],
            "schedule_uploaded": any(
                p.project_name == proj for p in positions
            ),
            "exception_count": rec["exception_count"],
            "exception_rate": rate,
            "deduction_amount": round(rec["deduction"], 2),
            "last_audit_at": rec["last_audit_at"] or "-",
        })

    exception_type_distribution = [
        {"type": k, "count": v} for k, v in type_counter.items() if v > 0
    ]

    # 扣款归因：按金额降序，给出占比、次数与单次成本（区分高频低损 / 低频高损）
    breakdown_total = sum(type_amount.values())
    deduction_breakdown = [
        {
            "type": label,
            "amount": round(amount, 2),
            "share_pct": round(amount / breakdown_total * 100, 1) if breakdown_total else 0,
            "count": type_counter.get(label, 0),
            "unit_cost": round(amount / type_counter[label], 2)
            if type_counter.get(label) else 0,
        }
        for label, amount in sorted(
            type_amount.items(), key=lambda kv: kv[1], reverse=True
        )
        if amount > 0
    ]
    # 不产生扣款但需关注的预警项
    warning_stats = {
        "mid_clock_issue_count": type_counter.get("中间卡异常", 0),
        "overtime_warning_count": overtime_warnings,
        "affected_employees": affected_employees,
    }
    # 供应商扣款排行：领导可直接据此追责
    supplier_total = sum(v["deduction"] for v in supplier_stats.values())
    supplier_ranking = [
        {
            "supplier": name,
            "deduction": round(rec["deduction"], 2),
            "share_pct": round(rec["deduction"] / supplier_total * 100, 1) if supplier_total else 0,
            "project_count": len(rec["projects"]),
            "projects": sorted(rec["projects"]),
        }
        for name, rec in sorted(
            supplier_stats.items(), key=lambda kv: kv[1]["deduction"], reverse=True
        )
        if rec["deduction"] > 0
    ]

    monthly_trend: list[dict] = []
    db = next(get_db())
    try:
        for m in _last_n_months(6):
            rows = (
                db.query(AuditResult)
                .filter(AuditResult.audit_month == m)
                .all()
            )
            ded = 0.0
            exc = 0
            sch = 0
            for r in rows:
                data = _parse_results_json(r.results_json)
                mt = audit_totals_metrics(data)
                ded += float(mt.get("total_deduction", 0) or 0)
                exc += int(mt.get("confirmed_count", 0) or 0)
                sch += int(
                    sum(1 for d in (data.get("slot_details") or [])
                        if d.get("status") not in ("休息", "请假"))
                ) or 0
            monthly_trend.append({
                "month": m,
                "exception_rate": round(exc / sch * 100, 1) if sch > 0 else 0,
                "deduction": round(ded, 2),
            })
    finally:
        db.close()

    # 风险项目 = 异常率超过阈值的项目（按异常率降序）；「当月未审核」在前端单独成卡
    risk_projects = [
        {
            "project_name": p["project_name"],
            "exception_rate": p["exception_rate"],
            "audit_status": p["audit_status"],
            "reason": f"异常率超过 {EXCEPTION_RATE_THRESHOLD:g}%",
        }
        for p in sorted(project_usage, key=lambda x: x["exception_rate"], reverse=True)
        if p["exception_rate"] > EXCEPTION_RATE_THRESHOLD
    ]

    avg_rate = (
        round(weighted_exceptions / weighted_schedule * 100, 1)
        if weighted_schedule > 0 else 0
    )
    # 完成率按「已确认（status=已确认）」口径：项目确认闭环才算完成；
    # 另给一个审核覆盖率（已审核含待确认），避免只看完成率误判为「系统没用起来」。
    completion_rate = (
        round(len(confirmed_projects) / len(all_projects) * 100, 1)
        if all_projects else 0
    )
    audit_coverage_rate = (
        round(len(audited_projects) / len(all_projects) * 100, 1)
        if all_projects else 0
    )
    confirm_rate = (
        round(len(confirmed_projects) / len(audited_projects) * 100, 1)
        if audited_projects else 0
    )

    # 业态维度聚合（同一项目的多条业态记录按业态归并）
    business_stats: dict[str, dict] = defaultdict(lambda: {
        "projects": set(), "deduction": 0.0, "exception_count": 0, "schedule_count": 0,
    })
    for r in audits:
        data = _parse_results_json(r.results_json)
        mt = audit_totals_metrics(data)
        slot = sum(
            1 for d in (data.get("slot_details") or [])
            if d.get("status") not in ("休息", "请假")
        )
        key = r.business_type or "未分类"
        rec = business_stats[key]
        rec["projects"].add(r.project_name)
        rec["deduction"] += float(mt.get("total_deduction", 0) or 0)
        rec["exception_count"] += int(mt.get("confirmed_count", 0) or 0)
        rec["schedule_count"] += slot
    business_type_stats = [
        {
            "business_type": k,
            "project_count": len(v["projects"]),
            "exception_rate": round(v["exception_count"] / v["schedule_count"] * 100, 1) if v["schedule_count"] else 0,
            "deduction_amount": round(v["deduction"], 2),
        }
        for k, v in sorted(business_stats.items(), key=lambda kv: kv[0])
    ]

    # 环比：与上一个自然月对比
    prev_deduction, prev_rate = _month_metrics(_prev_month(month))
    deduction_mom = (
        round((total_deduction - prev_deduction) / prev_deduction * 100, 1)
        if prev_deduction else None
    )
    rate_mom = round(avg_rate - prev_rate, 1) if prev_deduction or prev_rate else None

    return {
        "audit_month": month,
        "available_months": available_months,
        "exception_rate_threshold": EXCEPTION_RATE_THRESHOLD,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kpi": {
            "total_projects": len(all_projects),
            "audited_projects": len(audited_projects),
            "confirmed_projects": len(confirmed_projects),
            "pending_confirm_projects": len(pending_confirm_projects),
            "pending_projects": len(pending_projects),
            "confirm_rate": confirm_rate,
            "audit_coverage_rate": audit_coverage_rate,
            "total_deduction": round(total_deduction, 2),
            "avg_exception_rate": avg_rate,
            "completion_rate": completion_rate,
            "over_threshold_projects": len(risk_projects),
            "prev_month": _prev_month(month),
            "prev_deduction": prev_deduction,
            "prev_exception_rate": prev_rate,
            "deduction_mom_pct": deduction_mom,
            "rate_mom_pt": rate_mom,
        },
        "business_type_stats": business_type_stats,
        "project_usage": project_usage,
        "exception_type_distribution": exception_type_distribution,
        "deduction_breakdown": deduction_breakdown,
        "warning_stats": warning_stats,
        "supplier_ranking": supplier_ranking,
        "monthly_trend": monthly_trend,
        "risk_projects": risk_projects,
    }


def project_summary(project_name: str) -> dict:
    """项目账号驾驶舱：仅统计本项目「已确认」的最终版审核结果。

    过程版本（重新审核覆盖前）不会单独落库，同一定位键只保留最新一条，
    因此「已确认」状态即最终版口径。
    """
    db = next(get_db())
    try:
        rows = (
            db.query(AuditResult)
            .filter(AuditResult.project_name == project_name)
            .filter(AuditResult.status == "已确认")
            .order_by(AuditResult.audit_month.desc())
            .all()
        )
    finally:
        db.close()

    details: list[dict] = []
    total_schedule = 0
    total_exceptions = 0
    total_deduction = 0.0
    for r in rows:
        data = _parse_results_json(r.results_json)
        metrics = audit_totals_metrics(data)
        schedule_count = sum(
            1 for d in (data.get("slot_details") or [])
            if d.get("status") not in ("休息", "请假")
        )
        exc = int(metrics.get("confirmed_count", 0) or 0)
        ded = round(float(metrics.get("total_deduction", 0) or 0), 2)
        total_schedule += schedule_count
        total_exceptions += exc
        total_deduction += ded
        details.append({
            "project_name": r.project_name,
            "business_type": r.business_type,
            "service_type": r.service_type,
            "audit_month": r.audit_month,
            "status": r.status,
            "schedule_count": schedule_count,
            "exception_count": exc,
            "exception_rate": (
                round(exc / schedule_count * 100, 1) if schedule_count > 0 else 0
            ),
            "deduction_amount": ded,
            "confirmed_at": r.confirmed_at or (
                r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else ""
            ),
        })

    return {
        "project_name": project_name,
        "kpi": {
            "confirmed_count": len(details),
            "schedule_count": total_schedule,
            "exception_count": total_exceptions,
            "deduction_amount": round(total_deduction, 2),
        },
        "details": details,
    }
