"""项目 Excel 解析器 — 将项目考勤表解析为 PositionInfo / Position 模型。

表格结构（3 个 Sheet）：
  1. 基础信息      → 项目名称、业态、外包公司、约定/实际岗位数
  2. 合同编制表    → 每个岗位的编制信息（人员、工时、单价等）
  3. 排班表(排班情况) → 每个岗位每天排了谁（槽位级，含休息/缺岗/人名三态）
                       排班表是岗位表的子表，解析后挂到对应 Position.slots 上。
"""
from pathlib import Path
from openpyxl import load_workbook
import re
from datetime import datetime, date, time
from typing import Any

from app.api.v2.models.position_models import PositionInfo, Position, ScheduleSlot
from app.api.v2.utils.audit_common import (
    normalize_position_name,
    normalize_business_type,
    classify_schedule_cell,
    strip_position_time_suffix,
)


SCHEDULE_ALIASES = ["排班表", "排班", "排班情况", "考勤表", "月度排班", "班次", "考勤"]

# 排班表岗位名 → 合同编制表岗位名 的映射
SCHEDULE_TO_CONTRACT_NAME = {
    "领班": "领班",
    "领班13.5h": "领班",
    "1#写字楼": "1#、2#写字楼",
    "2#写字楼": "1#、2#写字楼",
    "酒店保洁": "酒店楼层",  # 酒店保洁的楼层部分对应酒店楼层
    "酒店外广场": "酒店外广场",
    "停车场及广场保洁": "停车场及广场保洁",
    "垃圾房": "垃圾房",
}


def _map_schedule_position_to_contract(schedule_pos: str) -> str:
    """把排班表的岗位名映射到合同编制表的岗位名。"""
    cleaned = strip_position_time_suffix(schedule_pos)
    # 先尝试精确匹配
    if cleaned in SCHEDULE_TO_CONTRACT_NAME:
        return SCHEDULE_TO_CONTRACT_NAME[cleaned]
    # 再尝试前缀匹配（仅当 key 是 cleaned 的前缀且 cleaned 更长时才匹配）
    # 例如 "领班xxx" → "领班"，但 "夜班领班" 不会误匹配到 "领班"
    for sched_name, contract_name in SCHEDULE_TO_CONTRACT_NAME.items():
        if len(cleaned) > len(sched_name) and cleaned.startswith(sched_name):
            return contract_name
    return cleaned


def _infer_month_from_filename(filename: str) -> str:
    """从文件名推断审核月份，格式 YYYY-MM。"""
    match = re.search(r"(20\d{2})[-年._]?(\d{1,2})", str(filename))
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    match = re.search(r"(\d{1,2})月", str(filename))
    if match:
        month = int(match.group(1))
        year = 2026
        return f"{year}-{month:02d}"
    return ""


def parse_project_excel(path: str | Path, audit_month: str = "") -> list[PositionInfo]:
    """解析项目考勤表，返回 PositionInfo 列表（一个业态一个）。

    同时把第 3 个 Sheet（排班表）解析为排班槽位，挂到对应岗位的 slots 上，
    形成「岗位表 : 排班子表」的主从结构，供岗位履约审核使用。

    Args:
        path:        项目考勤表路径。
        audit_month: 审核月份 'YYYY-MM'（优先于从文件名推断；真实流程里由项目选择决定）。
    """
    wb = load_workbook(str(path), data_only=True)
    sheet_names = wb.sheetnames
    audit_month = audit_month or _infer_month_from_filename(str(path))

    # --- 1. 解析基础信息 ---
    info_sheet = _find_sheet(sheet_names, wb, ["基础信息", "项目基础信息", "Sheet1"])
    base_info_list = _parse_base_info(info_sheet)

    # --- 2. 解析合同编制表 ---
    contract_sheet = _find_sheet(sheet_names, wb, ["合同编制表", "编制表", "Sheet2"])
    contract_positions = _parse_contract_positions(contract_sheet)

    # --- 3. 按业态聚合 ---
    result = []
    for info in base_info_list:
        biz_type = info["business_type"]

        # 按业态筛选岗位（用合同编制表的业态列匹配基础信息的业态）
        positions = [p for bt, p in contract_positions if bt == biz_type]

        position_info = PositionInfo(
            project_name=info["project_name"],
            business_type=biz_type,
            supplier=info["supplier"],
            contracted_count=info["contracted_count"],
            actual_count=sum(p.actual_count for p in positions),
            positions=positions,
        )
        result.append(position_info)

    # --- 4. 解析排班表（第 3 个 Sheet）→ 槽位，挂接到对应岗位下（1 岗位 : N 排班） ---
    slot_tuples = parse_schedule_sheet(wb, audit_month)
    unmatched = _attach_slots_to_positions(result, slot_tuples)
    if unmatched:
        print(f"[解析] {unmatched} 个排班槽位未匹配到编制表岗位（已生成占位岗位保留数据）")

    return result


def parse_schedule_sheet(wb, audit_month: str) -> list[tuple[ScheduleSlot, str, str, str]]:
    """把月度排班表解析为「排班槽位」列表，返回 (slot, position_name, raw_position, business_type) 元组。

    position_name 和 raw_position 仅用于匹配挂接，挂接后丢弃。
    business_type 用于将占位岗位挂到正确的业态下。
    """
    sheet_name = _find_sheet(wb.sheetnames, wb, SCHEDULE_ALIASES)
    if not sheet_name:
        return []
    ws = sheet_name
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    merged = _merged_cell_values(ws)

    header_row_idx = 0
    for idx in range(min(6, len(rows))):
        vals = [str(v).strip() for v in rows[idx] if v not in (None, "")]
        if any(v.isdigit() for v in vals) and any(k in " ".join(vals) for k in ("岗位", "区域", "姓名")):
            header_row_idx = idx
            break
    headers = [str(v).strip() if v is not None else "" for v in rows[header_row_idx]]
    business_idx = _find_idx(headers, ["业态", "业务类型", "服务类型"])
    position_idx = _find_idx(headers, ["岗位名称", "岗位"])
    area_idx = _find_idx(headers, ["固定区域", "区域", "责任区域"])
    if position_idx is None:
        position_idx = 1
    if business_idx is None and position_idx != 0:
        business_idx = 0

    day_columns = [(idx, day) for idx, h in enumerate(headers) if (day := _parse_day_header(h)) is not None]

    result: list[tuple[ScheduleSlot, str, str]] = []
    current_business = ""
    slot_counter: dict[str, int] = {}
    for source_row_no in range(header_row_idx + 2, len(rows) + 1):
        values = [_cell(v) for v in rows[source_row_no - 1]]
        business = _merged_or(values, merged, source_row_no, business_idx)
        business = str(business).strip() if business not in ("", None) else current_business
        if business:
            current_business = business
        raw_position = str(_merged_or(values, merged, source_row_no, position_idx) or "").strip()
        if not raw_position:
            continue
        area = str(_merged_or(values, merged, source_row_no, area_idx) or "").strip()
        position = strip_position_time_suffix(raw_position)
        counter_key = f"{position}|{area}"
        slot_counter[counter_key] = slot_counter.get(counter_key, 0) + 1
        daily = {}
        if len(audit_month) == 6 and audit_month.isdigit():
            month_fmt = f"{audit_month[:4]}-{audit_month[4:]}"
        elif "-" in audit_month:
            month_fmt = audit_month
        else:
            month_fmt = audit_month
        kind_to_status = {"person": "出勤", "rest": "休息", "leave": "请假", "shortage": "缺岗"}
        for col_idx, day in day_columns:
            value = _merged_or(values, merged, source_row_no, col_idx)
            cell = classify_schedule_cell(value)
            daily[f"{month_fmt}-{day:02d}"] = [{"names": cell["names"], "status": kind_to_status.get(cell["kind"], "休息")}]
        slot = ScheduleSlot(
            area=area,
            slot_index=slot_counter[counter_key],
            daily=daily,
        )
        result.append((slot, position, raw_position))
    return result


def _attach_slots_to_positions(
    position_infos: list[PositionInfo],
    slot_tuples: list[tuple[ScheduleSlot, str, str]],
) -> int:
    """把排班槽位挂到对应岗位（岗位表的子表），返回未匹配到编制表岗位的槽位数。

    同名岗位按出现顺序轮询分配槽位，避免所有槽位都挂到第一个同名岗位上。
    slot_tuples: (slot, position_name, raw_position)，后两个仅用于匹配，挂接后丢弃。
    """
    pos_index: dict[str, list] = {}
    for pi in position_infos:
        for p in pi.positions:
            key = strip_position_time_suffix(p.position_name)
            pos_index.setdefault(key, []).append((pi.business_type, p))

    name_counter: dict[str, int] = {}

    unmatched = 0
    for slot, position_name, _raw_position in slot_tuples:
        contract_pos_name = _map_schedule_position_to_contract(position_name)
        np_ = strip_position_time_suffix(contract_pos_name)
        cands = pos_index.get(np_)
        target = None
        if cands:
            idx = name_counter.get(np_, 0) % len(cands)
            name_counter[np_] = idx + 1
            target = cands[idx][1]
        if target is None:
            target = _ensure_synthetic_position(position_infos, position_name)
            unmatched += 1
        if target is not None:
            target.slots.append(slot)
    return unmatched


def _ensure_synthetic_position(position_infos: list[PositionInfo], position_name: str) -> Position | None:
    """排班表有岗位但编制表里没有时，生成占位岗位保留数据。"""
    if not position_infos:
        return None
    pi = position_infos[0]
    pos = Position(position_name=position_name)
    pi.positions.append(pos)
    return pos


def _merged_cell_values(ws) -> dict:
    """展开合并单元格，使区域内每个坐标都能取到左上角的值。"""
    values = {}
    for rng in ws.merged_cells.ranges:
        top_left = ws.cell(rng.min_row, rng.min_col).value
        if top_left in (None, ""):
            continue
        for row_no in range(rng.min_row, rng.max_row + 1):
            for col_no in range(rng.min_col, rng.max_col + 1):
                values[(row_no, col_no)] = top_left
    return values


def _merged_or(values: list, merged: dict, row_no: int, col_idx: int | None):
    """取槽位行的单元格值，合并单元格回落到左上角的值。col_idx 为 0 基。"""
    if col_idx is None or col_idx >= len(values):
        value = None
    else:
        value = values[col_idx]
    if value in ("", None):
        value = merged.get((row_no, (col_idx or 0) + 1))
    return value


def _cell(value) -> Any:
    if value is None:
        return ""
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value).strip()


def _find_idx(headers: list[str], keywords: list[str]) -> int | None:
    for idx, h in enumerate(headers):
        for kw in keywords:
            if kw in h:
                return idx
    return None


def _parse_day_header(h) -> int | None:
    """从表头解析日期列的数字（兼容 '1'、'1日'、'2026-07-01' 等）。"""
    t = str(h).strip()
    m = re.match(r"^(\d{1,2})", t)
    return int(m.group(1)) if m else None


def _find_sheet(sheet_names: list[str], wb, aliases: list[str]):
    """按别名查找 Sheet。"""
    for name in sheet_names:
        for alias in aliases:
            if alias in name:
                return wb[name]
    # fallback: 返回第一个 sheet
    return wb[sheet_names[0]]


def _safe_float(value, default=0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_base_info(ws) -> list[dict]:
    """解析基础信息 Sheet。
    列: 项目名称, 业态, 建筑面积, 可收费面积, 保洁外包公司,
        合同开始, 合同结束, 合同约定岗位数, 实际在岗岗位数, 合同金额
    """
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    result = []
    last_supplier = ""
    for row in rows:
        if not row[0] or not _safe_str(row[0]):
            continue
        contracted = _safe_float(row[7])
        actual = _safe_float(row[8])
        business_type = _safe_str(row[1])
        if not business_type or (contracted <= 0 and actual <= 0):
            continue
        project_name = _safe_str(row[0]).replace("项目", "")
        if len(project_name) > 100:
            continue
        raw_supplier = row[4]
        supplier = _extract_supplier_name(raw_supplier, row)
        if not supplier:
            supplier = last_supplier
        if supplier:
            last_supplier = supplier
        result.append({
            "project_name": project_name,
            "business_type": business_type,
            "supplier": supplier,
            "contracted_count": int(contracted),
            "actual_count": int(actual),
        })
    return result


def _extract_supplier_name(raw_value, row) -> str:
    """从基础信息行提取外包公司名称，跳过纯数字的合同编号。"""
    text = _safe_str(raw_value)
    if text and not text.isdigit() and len(text) > 2:
        return text
    for cell in row:
        cell_text = _safe_str(cell)
        if (cell_text
                and not cell_text.isdigit()
                and len(cell_text) > 4
                and any(kw in cell_text for kw in ("公司", "服务", "物业", "保洁", "保安", "环境"))):
            return cell_text
    return text if text and not text.isdigit() else ""


def _detect_contract_columns(headers: list[str]) -> dict[str, int]:
    """从表头自动检测列索引，兼容不同列顺序/有无"岗位归属"列的 Excel。

    关键词匹配优先级：精确包含 → 模糊包含。
    """
    col_map: dict[str, int] = {}
    for i, h in enumerate(headers):
        h_lower = h.replace(" ", "").replace("（", "(").replace("）", ")")
        if "项目名称" in h_lower:
            col_map["project_name"] = i
        elif "业态" in h_lower:
            col_map["business_type"] = i
        elif "岗位名称" in h_lower:
            col_map["position_name"] = i
        elif "岗位归属" in h_lower or "岗位类型" in h_lower:
            col_map["position_type"] = i
        elif "责任区域" in h_lower or ("区域" in h_lower and "岗位" not in h_lower):
            col_map["area"] = i
        elif "人员姓名" in h_lower or "人员" in h_lower:
            col_map["staff"] = i
        elif "岗位时间" in h_lower or "班次时间" in h_lower or ("时间" in h_lower and "岗位" in h_lower):
            col_map["shift_time"] = i
        elif "日时长" in h_lower:
            col_map["daily_hours"] = i
        elif "月总时长" in h_lower or "月时长" in h_lower:
            col_map["monthly_hours"] = i
        elif "单价" in h_lower:
            col_map["hourly_rate"] = i
        elif "月度合价" in h_lower or "合价" in h_lower:
            col_map["monthly_total"] = i
        elif "中间卡" in h_lower:
            col_map["mid_clock"] = i
        elif "实际岗位数" in h_lower or "实际人数" in h_lower or "实际" in h_lower:
            col_map["actual_count"] = i
        elif "跨天" in h_lower:
            col_map["cross_midnight"] = i
    return col_map


def _parse_contract_positions(ws) -> list[tuple[str, Position]]:
    """解析合同编制表。

    使用表头自动检测列索引，兼容有无"岗位归属"列的不同 Excel 格式。
    当缺少"岗位归属"列时，不会因列偏移导致 shift_time / daily_hours 等字段错位。

    返回 (业态, Position) 元组列表。
    """
    all_rows = list(ws.iter_rows(values_only=True))
    if not all_rows:
        return []

    headers = [_safe_str(v) for v in all_rows[0]]
    col_map = _detect_contract_columns(headers)

    pos_name_idx = col_map.get("position_name", 2)
    biz_idx = col_map.get("business_type", 1)

    rows = all_rows[1:]
    positions = []
    last_biz_type = ""
    for row in rows:
        if len(row) <= pos_name_idx:
            continue
        pos_name = _safe_str(row[pos_name_idx])
        if not pos_name:
            continue
        biz_type = _safe_str(row[biz_idx]) if len(row) > biz_idx else ""
        if biz_type:
            last_biz_type = biz_type

        def _col(name, default=""):
            idx = col_map.get(name)
            if idx is None or idx >= len(row):
                return default
            return row[idx]

        staff_str = _safe_str(_col("staff", ""))
        position = Position(
            position_name=pos_name,
            position_type=_safe_str(_col("position_type", "")),
            staff_list=[s.strip() for s in staff_str.split("、") if s.strip()] if staff_str else [],
            shift_time=_safe_str(_col("shift_time", "")),
            daily_hours=_safe_float(_col("daily_hours", 0)),
            monthly_hours=_safe_float(_col("monthly_hours", 0)),
            hourly_rate=_safe_float(_col("hourly_rate", 0)),
            monthly_total=_safe_float(_col("monthly_total", 0)),
            actual_count=int(_safe_float(_col("actual_count", 0))),
            mid_clock_time=_safe_str(_col("mid_clock", "")),
            is_cross_midnight=_safe_str(_col("cross_midnight", "")) == "是",
        )
        positions.append((last_biz_type, position))
    return positions
