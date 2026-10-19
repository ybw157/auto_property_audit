"""岗位履约审核（槽位级）：排班表 × BI 打卡。

审计单元是「岗位槽位」而不是具体的人 —— 我们只关心这个岗位当天有没有人上班、
上的人是谁（用于定位缺岗由谁补），但对外结论只给三态：有人 / 缺岗 / 待复核。

判定口径（上游立场：扣的是外包公司的钱，不追问个人）：
- 空格 / 休息 / 请假  → 当天该岗本就无人，不计审核（不扣）
- 单元格显式写「缺岗」→ 确定缺岗，计入扣款侧（日服务费 × 缺编系数）
- 单元格显式写「减岗」→ 计划性减员，确定扣款但仅按 1 倍日服务费（不乘缺编系数）
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
from app.api.v2.models.schedule_models import Shift
from app.api.v2.core.constants import AuditStatus
from app.api.v2.utils.audit_common import (
    normalize_employee_name,
    normalize_position_name,
    normalize_business_type,
    parse_time_value,
    time_to_minutes,
    resolve_cross_midnight,
    split_cross_day_clocks,
    parse_position_shifts,
    get_shift_for_date,
    get_next_date,
    daily_service_fee,
    weekday_adjusted_daily_hours,
    round_money,
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
    m_am = re.match(r"(\d{4})-?(\d{2})", str(audit_month or ""))
    if m_am:
        prefix = f"{m_am.group(1)}-{m_am.group(2)}"
    else:
        prefix = str(audit_month or "")
    return f"{prefix}-{day:02d}"


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
    """从 Position 解析班次，构建 (归一化姓名,日期)->班次，
    供跨天打卡拆分（夜班次日的下班卡归属前一天）使用。

    班次按「岗位名内嵌时间段优先、shift_time 字段兜底」解析（一岗多班场景下
    shift_time 是多班合并文本，直接取首段会错配），再按当天星期取对应班次。

    同时按「编制表 cross_midnight 字段优先、时间数值关系兜底」解析跨夜标志，
    与 S04 考勤审核的跨夜判定保持一致。
    """
    index: dict[tuple[str, str], Any] = {}
    for pi in position_infos:
        for p in pi.positions:
            shifts = parse_position_shifts(p.position_name, p.shift_time)
            for slot in p.slots:
                for work_date, cells in slot.daily.items():
                    start, end = get_shift_for_date(shifts, work_date)
                    if start and end:
                        shift = Shift(shift_name=p.position_name, start_time=start, end_time=end)
                        is_cross = resolve_cross_midnight(p.cross_midnight_raw, start, end)
                    else:
                        # 无班次时间时跨天判定退化为 False，打卡不拆分（与 audit_common.split_cross_day_clocks 兜底一致）
                        shift = None
                        is_cross = False
                    for cell in cells:
                        for name in cell.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                index[(nn, work_date)] = (shift, is_cross)
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
    entry = person_shift_index.get((name, get_next_date(work_date)))
    # prev_shift 是「前一天夜班」；次日清晨的卡若早于该夜班下班，属前一天
    prev_shift = entry[0] if entry else None
    is_cross = entry[1] if entry else None
    today_clocks, prev_clocks = split_cross_day_clocks(clocks, prev_shift, is_cross)
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
    # 解析岗位班次信息，附带在每个 slot_detail 里。
    # 岗位名内嵌时间段优先（一岗多班时 shift_time 是多班合并文本，取首段会错配），
    # 再按当天星期取对应班次。
    shifts = parse_position_shifts(position.position_name, position.shift_time)
    shift_start, shift_end = get_shift_for_date(shifts, work_date)
    if not shift_start or not shift_end:
        is_cross = False
    else:
        is_cross = resolve_cross_midnight(position.cross_midnight_raw, shift_start, shift_end)

    def _base_detail(**extra) -> dict:
        """构造 slot_detail 基础结构，自动附带班次信息。"""
        return {
            "work_date": work_date,
            "position": pos_name,
            "slot_index": slot.slot_index,
            "area": slot.area,
            "slot_hours": slot.slot_hours,
            "shift_start": shift_start,
            "shift_end": shift_end,
            "is_cross_midnight": is_cross,
            "cross_day_excluded": [],
            **extra,
        }

    statuses = [c.get("status", "") for c in cells]
    if all(s in ("休息", "请假") for s in statuses):
        kind = "请假" if any(s == "请假" for s in statuses) else "休息"
        return _base_detail(
            scheduled=[],
            status=kind,
            is_shortage=False,
            actual_present=[],
            note="排班表标记" + kind,
        )

    has_shortage_marker = any(c.get("status", "") == "缺岗" for c in cells)
    has_reduction_marker = any(c.get("status", "") == "减岗" for c in cells)
    persons = []
    for c in cells:
        for n in c.get("names", []):
            nn = normalize_employee_name(n)
            if nn:
                persons.append(nn)
    persons = list(dict.fromkeys(persons))

    if has_shortage_marker:
        return _base_detail(
            scheduled=persons,
            status="缺岗",
            is_shortage=True,
            actual_present=[],
            note="排班表显式标注缺岗",
        )

    if has_reduction_marker:
        return _base_detail(
            scheduled=persons,
            status="减岗",
            is_shortage=True,
            actual_present=[],
            note="排班表显式标注减岗",
        )

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
        return _base_detail(
            scheduled=persons,
            status="有人",
            is_shortage=False,
            actual_present=present,
            note="排班人员当天有打卡",
        )

    own_sub = []
    for s in staff:
        if s in persons:
            continue
        ok, _, _ = _is_on_duty(s, work_date, attendance_by_person_date, person_shift_index)
        if ok:
            own_sub.append(s)
    if own_sub:
        return _base_detail(
            scheduled=persons,
            status="有人",
            is_shortage=False,
            actual_present=own_sub,
            note=f"排班人员未到，本岗人员{'、'.join(own_sub)}顶班",
        )

    others = [
        n for n in attendance_by_date.get(work_date, set())
        if n not in persons and n not in staff
    ]
    if others:
        if SUBSTITUTE_OTHER_POLICY == "present":
            return _base_detail(
                scheduled=persons,
                status="有人",
                is_shortage=False,
                actual_present=others,
                note=f"排班人员未到，其他岗位人员{'、'.join(others[:3])}当天打卡（按有人处理）",
            )
        if SUBSTITUTE_OTHER_POLICY == "shortage":
            return _base_detail(
                scheduled=persons,
                status="缺岗",
                is_shortage=True,
                actual_present=[],
                note=f"排班人员未到，仅其他岗位人员{'、'.join(others[:3])}打卡（按缺岗处理）",
            )
        return _base_detail(
            scheduled=persons,
            status="待复核",
            is_shortage=False,
            actual_present=others,
            note=f"排班人员未到，现场有其他岗位人员{'、'.join(others[:3])}打卡，需确认是否顶岗",
        )

    return _base_detail(
        scheduled=persons,
        status="缺岗",
        is_shortage=True,
        actual_present=[],
        note="排班人员未到且项目当天无人打卡",
    )


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
    return {"slot_details": slot_details, "summary": summary, "status": AuditStatus.AUDITED}


def _build_summary(
    slot_details: list[dict],
    position_infos: list[PositionInfo],
    absence_coefficient: float = 1.0,
) -> list[dict]:
    """按 (岗位, 槽位序号) 聚合缺岗/减岗/待复核统计，并估算缺岗扣款。

    absence_coefficient: 缺编扣款倍数（合同字段 contract_deduction_coefficient），
    缺编扣款 = 缺岗天数 × 日服务费 × 该系数 + 减岗天数 × 日服务费 × 1.0。
    """
    rate_map: dict[str, tuple] = {}
    for pi in position_infos:
        for p in pi.positions:
            rate_map[normalize_position_name(p.position_name)] = (
                p.hourly_rate, p.daily_hours, p.monthly_total, p.actual_count, pi.service_type,
                p.shift_time, p.monthly_rate,
            )

    grouped: dict[tuple[str, int], dict] = {}
    for d in slot_details:
        gkey = (d["position"], d["slot_index"])
        item = grouped.setdefault(gkey, {
            "position": d["position"],
            "slot_index": d["slot_index"],
            "slot_hours": d.get("slot_hours", 0.0),  # 该班次实际日时长（早/晚/全天），取自排班表岗位名
            "required_days": 0,
            "normal_days": 0,
            "shortage_days": 0,
            "reduction_days": 0,
            "pending_days": 0,
            "rest_days": 0,
            "shortage_dates": [],
            "reduction_dates": [],
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
        elif status == "减岗":
            item["reduction_days"] += 1
            item["reduction_dates"].append(d["work_date"])
        elif status == "待复核":
            item["pending_days"] += 1
            item["pending_dates"].append(d["work_date"])

    summary = []
    for (pos, slot_idx), item in grouped.items():
        rate, contract_hours, monthly_total, actual_count, service_type, shift_time, monthly_rate = rate_map.get(
            normalize_position_name(pos), (0.0, 0.0, 0.0, 0, "", "", 0.0))
        # 班次级时长优先：排班表把全天岗拆成早/晚两行时，缺岗应按「该班次实际时长」计费，
        # 而非合同编制表的全天 daily_hours（否则早班缺勤会按全天 13h 扣，即原 bug）。
        slot_hours = item.get("slot_hours", 0.0)
        effective_hours = slot_hours if slot_hours > 0 else contract_hours
        # 日服务费统一走 _daily_service_fee（保安=岗位单价÷30.42（月合价兜底），保洁=工时单价×日时长），
        # 半天槽位按 有效时长/日时长 折算；保洁口径下与「工时单价×有效时长」完全等价。
        fee = daily_service_fee(rate, contract_hours, monthly_total, actual_count, service_type, monthly_rate)
        # 星期分段班次的逐日时长（基线法）：仅当未命中班次级时长且分段可靠时启用；
        # 无分段或数据矛盾时 hours_map 为 None，逐日计费退化为现状的统一 per_day。
        hours_map = None
        if slot_hours <= 0 and (item["shortage_dates"] or item["reduction_dates"]):
            hours_map = weekday_adjusted_daily_hours(contract_hours, shift_time)

        def _per_day(hours: float) -> float:
            if fee and contract_hours > 0 and hours > 0:
                return float(round_money(fee * hours / contract_hours))
            return fee if fee else 0.0

        def _weekday_of(ds: str) -> int:
            try:
                return datetime.strptime(ds, "%Y-%m-%d").weekday()
            except (ValueError, TypeError):
                return -1

        # 每天最终扣款取整到元后求和，保证日明细与合计口径恒等
        if hours_map:
            amount = 0
            for ds in item["shortage_dates"]:
                amount += round_money(_per_day(hours_map.get(_weekday_of(ds), effective_hours)) * absence_coefficient)
            # 减岗按 1 倍日服务费（不乘缺编系数）
            red_amount = 0
            for ds in item["reduction_dates"]:
                red_amount += round_money(_per_day(hours_map.get(_weekday_of(ds), effective_hours)))
            item["shortage_amount"] = amount + red_amount
        else:
            per_day = _per_day(effective_hours)
            item["shortage_amount"] = (
                round_money(per_day * absence_coefficient) * item["shortage_days"]
                + round_money(per_day) * item["reduction_days"]
            ) if per_day else 0
        item["hourly_rate"] = rate
        item["daily_hours"] = effective_hours
        item["shortage_rate"] = (
            round(item["shortage_days"] / item["required_days"] * 100, 1)
            if item["required_days"] else 0.0
        )
        summary.append(item)
    summary.sort(key=lambda x: (x["position"], x["slot_index"]))
    return summary
