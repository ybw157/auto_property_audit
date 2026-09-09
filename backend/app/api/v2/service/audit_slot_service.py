"""岗位履约审核（槽位级）：排班表 × BI 打卡。

审计单元是「岗位槽位」而不是具体的人 —— 我们只关心这个岗位当天有没有人上班、
上的人是谁（用于定位缺岗由谁补），但对外结论只给三态：有人 / 缺岗 / 待复核。

判定口径（上游立场：扣的是外包公司的钱，不追问个人）：
- 空格 / 休息 / 请假  → 当天该岗本就无人，不计审核（不扣）
- 单元格显式写「缺岗」→ 确定缺岗，计入扣款侧
- 排了人 X：
    X 当天 BI 有打卡(含跨天拆分)        → 有人（确定）
    X 没打卡，但本岗编制内他人打卡       → 有人（顶班/换班，不扣）
    X 没打卡，仅其他岗位人员打卡         → 待复核（疑似顶班，需人工确认）
    X 没打卡，项目当天无人打卡           → 缺岗（确定）
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from app.api.v2.models.position_models import PositionInfo
from app.api.v2.models.position_models import ScheduleSlot
from app.api.v2.utils.audit_common import (
    normalize_employee_name,
    normalize_position_name,
    normalize_business_type,
    split_cross_day_clocks,
    shift_from_raw_position,
    get_next_date,
)


# ---- 业务口径开关（默认走谨慎路线，改动一处即可切换） ----
# 排班空格一律视为休息（不计入缺岗）。若改为 "shortage" 则空单元格也记缺岗。
UNSCHEDULED_EMPTY_POLICY = "ignore"
# 排班人没来、但其他岗位人员打卡时如何处理：
#   "pending"  → 待复核（默认，不直接放过也不直接扣）
#   "present"  → 算有人不扣
#   "shortage" → 算缺岗照扣
SUBSTITUTE_OTHER_POLICY = "pending"


def _norm_month(audit_month: str) -> str:
    """把 '202607' / '2026-07' 统一成 'YYYY-MM'。"""
    s = str(audit_month or "").strip()
    if not s:
        return ""
    m = re.match(r"(\d{4})[-年.]?(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return s


def _bi_day_to_iso(label: Any, audit_month: str) -> str:
    """把 BI 的 '1日' / '1' / '2026-07-01' 转成 ISO 日期。"""
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


def _build_bi_index(bi_records: list[dict], audit_month: str):
    """构建 BI 索引：(姓名,日期)->打卡列表、日期->在岗人集合。"""
    attendance_by_person_date: dict[tuple[str, str], list[str]] = defaultdict(list)
    attendance_by_date: dict[str, set[str]] = defaultdict(set)
    for rec in bi_records:
        name = normalize_employee_name(rec.get("employee_name", ""))
        if not name:
            continue
        att = rec.get("attendance", {}) or {}
        for day_label, clocks in att.items():
            iso = _bi_day_to_iso(day_label, audit_month)
            if not iso:
                continue
            cl = [str(c).strip() for c in (clocks or []) if c and str(c).strip()]
            if not cl:
                continue
            # 同一个人同一天可能多条记录，合并
            key = (name, iso)
            if key not in attendance_by_person_date:
                attendance_by_person_date[key] = []
                attendance_by_date[iso].add(name)
            attendance_by_person_date[key].extend(cl)
    return attendance_by_person_date, attendance_by_date


def _build_person_shift_index(position_infos: list[PositionInfo]) -> dict[tuple[str, str], Any]:
    """从 Position.shift_time 解析班次，构建 (归一化姓名,日期)->班次，
    供跨天打卡拆分（夜班次日的下班卡归属前一天）使用。
    """
    index: dict[tuple[str, str], Any] = {}
    for pi in position_infos:
        for p in pi.positions:
            shift = shift_from_raw_position(p.shift_time)
            for slot in p.slots:
                for work_date, cells in slot.daily.items():
                    for cell in cells:
                        for name in cell.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                index[(nn, work_date)] = shift
    return index


def _is_on_duty(
    name: str,
    work_date: str,
    attendance_by_person_date: dict,
    person_shift_index: dict,
) -> tuple[bool, list[str], list[str]]:
    """某人某天是否到岗。返回 (是否到岗, 当天有效打卡, 被归到前一天的卡)。"""
    clocks = attendance_by_person_date.get((name, work_date), [])
    if not clocks:
        return False, [], []
    prev_shift = person_shift_index.get((name, get_next_date(work_date)))
    # prev_shift 是「前一天夜班」；次日清晨的卡若早于该夜班下班，属前一天
    today_clocks, prev_clocks = split_cross_day_clocks(clocks, prev_shift)
    return (len(today_clocks) > 0), today_clocks, prev_clocks


def _audit_one_slot_day(
    position: Position,
    slot: ScheduleSlot,
    work_date: str,
    cells: list[dict],
    staff: set[str],
    attendance_by_person_date: dict,
    attendance_by_date: dict,
    person_shift_index: dict,
) -> dict | None:
    """判定一个槽位某一天的履约状态。返回 None 表示该天不计审核（休息/请假）。"""
    pos_name = position.position_name
    statuses = [c.get("status", "") for c in cells]
    if all(s in ("休息", "请假") for s in statuses):
        kind = "请假" if any(s == "请假" for s in statuses) else "休息"
        return {
            "work_date": work_date,
            "position": pos_name,
            "slot_index": slot.slot_index,
            "area": slot.area,
            "scheduled": [],
            "status": kind,
            "is_shortage": False,
            "actual_present": [],
            "note": "排班表标记" + kind,
            "cross_day_excluded": [],
        }

    has_shortage_marker = any(c.get("status", "") == "缺岗" for c in cells)
    persons = []
    for c in cells:
        for n in c.get("names", []):
            nn = normalize_employee_name(n)
            if nn:
                persons.append(nn)
    persons = list(dict.fromkeys(persons))

    if has_shortage_marker:
        return {
            "work_date": work_date,
            "position": pos_name,
            "slot_index": slot.slot_index,
            "area": slot.area,
            "scheduled": persons,
            "status": "缺岗",
            "is_shortage": True,
            "actual_present": [],
            "note": "排班表显式标注缺岗",
            "cross_day_excluded": [],
        }

    if not persons:
        return None

    on_duty, _, _ = _is_on_duty(
        persons[0], work_date, attendance_by_person_date, person_shift_index
    )
    if on_duty:
        present = []
        for p in persons:
            ok, _, _ = _is_on_duty(p, work_date, attendance_by_person_date, person_shift_index)
            if ok:
                present.append(p)
        return {
            "work_date": work_date,
            "position": pos_name,
            "slot_index": slot.slot_index,
            "area": slot.area,
            "scheduled": persons,
            "status": "有人",
            "is_shortage": False,
            "actual_present": present,
            "note": "排班人员当天有打卡",
            "cross_day_excluded": [],
        }

    own_sub = []
    for s in staff:
        if s in persons:
            continue
        ok, _, _ = _is_on_duty(s, work_date, attendance_by_person_date, person_shift_index)
        if ok:
            own_sub.append(s)
    if own_sub:
        return {
            "work_date": work_date,
            "position": pos_name,
            "slot_index": slot.slot_index,
            "area": slot.area,
            "scheduled": persons,
            "status": "有人",
            "is_shortage": False,
            "actual_present": own_sub,
            "note": f"排班人员未到，本岗人员{'、'.join(own_sub)}顶班",
            "cross_day_excluded": [],
        }

    others = [
        n for n in attendance_by_date.get(work_date, set())
        if n not in persons and n not in staff
    ]
    if others:
        if SUBSTITUTE_OTHER_POLICY == "present":
            return {
                "work_date": work_date, "position": pos_name,
                "slot_index": slot.slot_index, "area": slot.area,
                "scheduled": persons, "status": "有人", "is_shortage": False,
                "actual_present": others,
                "note": f"排班人员未到，其他岗位人员{'、'.join(others[:3])}当天打卡（按有人处理）",
                "cross_day_excluded": [],
            }
        if SUBSTITUTE_OTHER_POLICY == "shortage":
            return {
                "work_date": work_date, "position": pos_name,
                "slot_index": slot.slot_index, "area": slot.area,
                "scheduled": persons, "status": "缺岗", "is_shortage": True,
                "actual_present": [],
                "note": f"排班人员未到，仅其他岗位人员{'、'.join(others[:3])}打卡（按缺岗处理）",
                "cross_day_excluded": [],
            }
        return {
            "work_date": work_date, "position": pos_name,
            "slot_index": slot.slot_index, "area": slot.area,
            "scheduled": persons, "status": "待复核", "is_shortage": False,
            "actual_present": others,
            "note": f"排班人员未到，现场有其他岗位人员{'、'.join(others[:3])}打卡，需确认是否顶岗",
            "cross_day_excluded": [],
        }

    return {
        "work_date": work_date,
        "position": pos_name,
        "slot_index": slot.slot_index,
        "area": slot.area,
        "scheduled": persons,
        "status": "缺岗",
        "is_shortage": True,
        "actual_present": [],
        "note": "排班人员未到且项目当天无人打卡",
        "cross_day_excluded": [],
    }


def run_slot_audit(
    position_infos: list[PositionInfo],
    bi_records: list[dict],
    audit_month: str = "",
    absence_coefficient: float = 1.0,
) -> dict:
    """执行槽位级岗位履约审核，返回 {slot_details, summary, status}。

    Args:
        position_infos:      已含 slots 的岗位信息（来自 position_dao）。
        bi_records:          同项目同月份的 BI 考勤记录（来自 bi_dao.get_bi_by_project）。
        audit_month:         审核月份，'YYYY-MM' 或 'YYYYMM'。
        absence_coefficient: 缺编扣款倍数（合同缺编系数 contract_deduction_coefficient），
                             缺编扣款 = 缺岗天数 × 日服务费 × 该系数。
    """
    month = _norm_month(audit_month)
    attendance_by_person_date, attendance_by_date = _build_bi_index(bi_records, month)

    # 收集本岗编制名单（用于判断本岗内部顶班）
    pos_staff: dict[str, set[str]] = {}
    for pi in position_infos:
        for p in pi.positions:
            key = normalize_position_name(p.position_name)
            pos_staff[key] = {normalize_employee_name(s) for s in p.staff_list}

    person_shift_index = _build_person_shift_index(position_infos)

    slot_details: list[dict] = []
    for pi in position_infos:
        for p in pi.positions:
            key = normalize_position_name(p.position_name)
            staff = pos_staff.get(key, set())
            for slot in p.slots:
                for work_date in sorted(slot.daily.keys()):
                    detail = _audit_one_slot_day(
                        p, slot, work_date, slot.daily[work_date], staff,
                        attendance_by_person_date, attendance_by_date, person_shift_index,
                    )
                    if detail is not None:
                        slot_details.append(detail)

    summary = _build_summary(slot_details, position_infos, absence_coefficient)
    return {"slot_details": slot_details, "summary": summary, "status": "已审核"}


def _build_summary(
    slot_details: list[dict],
    position_infos: list[PositionInfo],
    absence_coefficient: float = 1.0,
) -> list[dict]:
    """按 (岗位, 槽位序号) 聚合缺岗/待复核统计，并估算缺岗扣款。

    absence_coefficient: 缺编扣款倍数（合同字段 contract_deduction_coefficient），
    缺编扣款 = 缺岗天数 × 日服务费 × 该系数。
    """
    rate_map: dict[str, tuple[float, float]] = {}
    for pi in position_infos:
        for p in pi.positions:
            rate_map[normalize_position_name(p.position_name)] = (
                p.hourly_rate, p.daily_hours,
            )

    grouped: dict[tuple[str, int], dict] = {}
    for d in slot_details:
        gkey = (d["position"], d["slot_index"])
        item = grouped.setdefault(gkey, {
            "position": d["position"],
            "slot_index": d["slot_index"],
            "required_days": 0,
            "normal_days": 0,
            "shortage_days": 0,
            "pending_days": 0,
            "rest_days": 0,
            "shortage_dates": [],
            "pending_dates": [],
        })
        status = d["status"]
        if status in ("休息", "请假"):
            item["rest_days"] += 1
            continue
        item["required_days"] += 1
        if status == "有人":
            item["normal_days"] += 1
        elif status == "缺岗":
            item["shortage_days"] += 1
            item["shortage_dates"].append(d["work_date"])
        elif status == "待复核":
            item["pending_days"] += 1
            item["pending_dates"].append(d["work_date"])

    summary = []
    for (pos, slot_idx), item in grouped.items():
        rate, hours = rate_map.get(normalize_position_name(pos), (0.0, 0.0))
        per_day = round(rate * hours, 2) if rate and hours else 0.0
        item["hourly_rate"] = rate
        item["daily_hours"] = hours
        item["shortage_amount"] = round(item["shortage_days"] * per_day * absence_coefficient, 2) if per_day else 0.0
        item["shortage_rate"] = (
            round(item["shortage_days"] / item["required_days"] * 100, 1)
            if item["required_days"] else 0.0
        )
        summary.append(item)
    summary.sort(key=lambda x: (x["position"], x["slot_index"]))
    return summary
