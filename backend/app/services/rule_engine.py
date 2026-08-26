from collections import Counter, defaultdict
from datetime import datetime, date, time, timedelta
from typing import Any
import re

from app.core.database import get_conn, json_dumps, json_loads, now_text
from openpyxl import load_workbook
from app.services.excel_parser import parse_project_workbook, parse_attendance_workbook, validate_project_workbook, find_sheet_name, SCHEDULE_ALIASES, parse_monthly_schedule

def run_audit(batch_id: int, project_path: str, attendance_path: str, selected_project: dict | None = None) -> dict:
    validation = validate_project_workbook(project_path)
    if not validation["valid"]:
        raise ValueError(validation["message"])
    data = parse_project_workbook(project_path)
    if selected_project:
        if selected_project.get("项目名称"):
            data["project_info"]["项目名称"] = selected_project["项目名称"]
        if selected_project.get("项目编码"):
            data["project_info"]["项目编码"] = selected_project["项目编码"]
        if selected_project.get("审核月份"):
            data["project_info"]["审核月份"] = selected_project["审核月份"]
            # 如果用户指定的审核月份与排班表解析时的月份不一致，用正确月份重新解析排班表
            audit_month = selected_project["审核月份"]
            if data["monthly_schedules"]:
                first_date = str(data["monthly_schedules"][0].get("work_date", ""))
                if first_date[:7] != audit_month[:7]:
                    wb = load_workbook(project_path, data_only=True)
                    schedule_ws = wb[find_sheet_name(wb, SCHEDULE_ALIASES)]
                    data["monthly_schedules"] = parse_monthly_schedule(schedule_ws, audit_month)
                    print(f"排班表月份校正：{first_date[:7]} -> {audit_month[:7]}")
    # 用户指定的业态（如"住宅"、"商业"）
    selected_business_type = str(selected_project.get("审核业态", "")).strip() if selected_project else ""

    # 解析BI考勤数据
    attendance_rows = parse_attendance_workbook(attendance_path) if attendance_path else []

    # 按当前审核项目过滤BI数据（BI导出文件可能包含多个项目）
    # 同一个项目在BI中可能有多个名称（别名），需要合并匹配
    current_project_name = selected_project.get("项目名称", "") if selected_project else ""
    if current_project_name and attendance_rows:
        # 项目别名映射：BI中可能用不同名称指代同一个项目
        project_aliases = {
            "南通金鹰世界": ["南通金鹰世界", "南通尚湖花园"],
            "南京金鹰世界": ["南京金鹰世界"],
            "南京金鹰花园": ["南京金鹰花园"],
        }
        match_names = project_aliases.get(current_project_name, [current_project_name])
        filtered_rows = [r for r in attendance_rows if r.get("项目") in match_names]
        if filtered_rows:
            attendance_rows = filtered_rows
            alias_note = f"（含别名：{','.join(match_names)}）" if len(match_names) > 1 else ""
            print(f"BI考勤数据已按项目过滤：{current_project_name}{alias_note}，保留 {len(filtered_rows)} 条记录")
        else:
            print(f"警告：BI考勤数据中未找到项目 {current_project_name} 的记录，将使用全部数据")

    # 注意：BI考勤数据不按业态过滤。原因：
    # 1. BI数据中业态字段可能不准确（如住宅人员被标为商业/未确定）
    # 2. 系统会根据排班(人员,日期)去BI数据中匹配打卡记录，天然实现按人员过滤
    # 业态过滤只作用于排班表和合同表。

    configs = load_configs()

    log(batch_id, "system", "模板校验", "模板校验", "template_validate", validation, {"valid": True}, "按Sheet名称读取，不按顺序读取")

    contracts = normalize_contracts(data["contract_staffing"])
    schedules = normalize_schedules(data["monthly_schedules"])
    shifts = normalize_shifts(data["shift_standards"])
    attendance = normalize_attendance(attendance_rows)

    # 按选定业态过滤排班（排班的business_type来自备注中的"业态：xxx"）
    if selected_business_type:
        selected_norm = normalize_business_type(selected_business_type)
        before = len(schedules)
        schedules = [s for s in schedules if normalize_business_type(s.get("business_type", "")) == selected_norm]
        contracts = [c for c in contracts if normalize_business_type(c.get("business_type", "")) == selected_norm]
        print(f"排班已按业态过滤：{selected_business_type}(归一化:{selected_norm})，保留 {len(schedules)}/{before} 条排班")

    if selected_business_type:
        audit_business_types = [selected_business_type]
    else:
        audit_business_types = infer_audit_business_types(attendance_rows)
    contracts, schedules = filter_scope_by_business_type(contracts, schedules, audit_business_types)
    configs = apply_rule_center_rules(configs, data["project_info"], audit_business_types)
    # 必须上传并启用合同、提取到扣款规则后才能审核
    active_contract = find_active_contract(data["project_info"], audit_business_types)
    if not active_contract:
        raise ValueError("未找到启用的合同。请先在合同管理中上传合同并启用，系统提取扣款规则后才能进行审核。")
    # 合同中的打卡次数等规则合并到configs（作为默认值，各服务类型可覆盖）
    contract_rules = active_contract.get("rules", {})
    if "required_clock_count" in contract_rules:
        configs["required_clock_count"] = contract_rules["required_clock_count"]
    # 校验保洁规则（主要服务类型）
    configs_by_service = configs.get("_configs_by_service", {})
    cleaning_configs = configs_by_service.get("保洁", configs)
    if not cleaning_configs.get("late_early_tiers"):
        raise ValueError("保洁合同扣款规则未提取完整（缺少迟到/早退分档规则）。请重新上传合同或联系管理员检查合同提取结果。")
    if not cleaning_configs.get("attendance_deduction_coefficient"):
        raise ValueError("保洁合同扣款系数未提取。请重新上传合同或联系管理员检查合同提取结果。")
    # 保安规则如果有合同也校验，没有保安合同不报错（可能该项目只有保洁）
    security_configs = configs_by_service.get("保安", {})
    if security_configs and not security_configs.get("late_early_tiers"):
        print("警告：保安合同扣款规则未提取完整，保安岗位将使用保洁规则")
    if selected_project and selected_project.get("审核月份"):
        schedules = align_schedule_month_to_selected_month(schedules, selected_project["审核月份"])

    attendance_by_person_date = {(r["employee_name"], r["work_date"]): r for r in attendance}
    attendance_by_date = defaultdict(list)
    for item in attendance:
        attendance_by_date[item["work_date"]].append(item)

    attendance_details, attendance_deductions = audit_attendance(batch_id, schedules, shifts, attendance_by_person_date, attendance_by_date, contracts, configs)
    position_fulfillment = build_schedule_audit_summary(attendance_details)
    exception_statistics = build_exception_statistics(attendance_details)
    deduction_summary = build_deduction_summary(position_fulfillment, attendance_deductions)
    summary = build_summary(position_fulfillment, attendance_details, deduction_summary)
    ai_analysis = build_ai_analysis(summary, exception_statistics, deduction_summary)

    return {
        "project_info": data["project_info"],
        "active_contract": find_active_contract(data["project_info"], audit_business_types),
        "audit_business_types": audit_business_types,
        "selected_business_type": selected_business_type,
        "contracts": contracts,
        "schedules": schedules[:1000],
        "shift_standards": shifts,
        "attendance_details": attendance_details,
        "position_fulfillment": position_fulfillment,
        "exception_statistics": exception_statistics,
        "attendance_deductions": attendance_deductions,
        "deduction_summary": deduction_summary,
        "summary": summary,
        "ai_analysis": ai_analysis,
    }

def load_configs() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key,value,value_type FROM rule_configs").fetchall()
    configs = {}
    for row in rows:
        value = row["value"]
        if row["value_type"] == "number":
            value = float(value)
        elif row["value_type"] == "boolean":
            value = str(value).lower() == "true"
        configs[row["key"]] = value
    return configs

def find_active_contract(project_info: dict, audit_business_types: list[str], service_type: str = "") -> dict | None:
    """查询当前项目+业态启用的合同信息，可选按服务类型过滤。"""
    project_name = str(project_info.get("项目名称") or "").strip()
    project_code = str(project_info.get("项目编码") or "").strip()
    business_types = [normalize_business_type(item) for item in audit_business_types if normalize_business_type(item)]
    with get_conn() as conn:
        for business_type in business_types or [""]:
            if service_type:
                row = conn.execute(
                    """
                    SELECT contract_name, contract_no, supplier, version, start_date, end_date, business_type, service_type, rules_json
                    FROM project_contracts
                    WHERE project_name=? AND business_type=? AND service_type=? AND status='active' AND is_active=1
                    ORDER BY id DESC LIMIT 1
                    """,
                    (project_name, business_type, service_type),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT contract_name, contract_no, supplier, version, start_date, end_date, business_type, service_type, rules_json
                    FROM project_contracts
                    WHERE project_name=? AND business_type=? AND status='active' AND is_active=1
                    ORDER BY id DESC LIMIT 1
                    """,
                    (project_name, business_type),
                ).fetchone()
            if row:
                rules = json_loads(row["rules_json"], {}) if row["rules_json"] else {}
                return {
                    "contract_name": row["contract_name"],
                    "contract_no": row["contract_no"],
                    "supplier": row["supplier"],
                    "version": row["version"],
                    "start_date": row["start_date"],
                    "end_date": row["end_date"],
                    "business_type": row["business_type"],
                    "service_type": row["service_type"] if "service_type" in row.keys() else "",
                    "rules": rules,
                }
    # 仅在未指定业态时才做不限定业态的回退匹配（指定了业态就必须匹配对应业态的合同）
    if not business_types:
        row = conn.execute(
            """
            SELECT contract_name, contract_no, supplier, version, start_date, end_date, business_type
            FROM project_contracts
            WHERE project_name=? AND status='active' AND is_active=1
            ORDER BY id DESC LIMIT 1
            """,
            (project_name,),
        ).fetchone()
        if row:
            return {
                "contract_name": row["contract_name"],
                "contract_no": row["contract_no"],
                "supplier": row["supplier"],
                "version": row["version"],
                "start_date": row["start_date"],
                "end_date": row["end_date"],
                "business_type": row["business_type"],
            }
    return None

def apply_rule_center_rules(configs: dict, project_info: dict, audit_business_types: list[str]) -> dict:
    """加载保安/保洁各自的合同规则，返回 configs_by_service = {"保洁": {...}, "保安": {...}}。
    不再合并覆盖，保留各服务类型独立规则。同时把保洁规则写入顶层configs保持兼容。
    """
    project_name = str(project_info.get("项目名称") or "").strip()
    project_code = str(project_info.get("项目编码") or "").strip()
    business_types = [normalize_business_type(item) for item in audit_business_types if normalize_business_type(item)]
    service_types = infer_service_types_from_business(audit_business_types)
    
    configs_by_service = {}
    updated = dict(configs)  # 顶层configs默认用系统配置
    
    with get_conn() as conn:
        for service_type in service_types:
            service_configs = dict(configs)  # 每个服务类型独立从系统默认开始
            row = None
            # 优先从 project_rule_center（人工确认的规则）读取
            for business_type in business_types or [""]:
                if project_code:
                    row = conn.execute(
                        """
                        SELECT rules_json FROM project_rule_center
                        WHERE project_code=? AND service_type=? AND IFNULL(business_type,'')=IFNULL(?, '') AND status IN ('已确认','待确认')
                        ORDER BY CASE status WHEN '已确认' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                        LIMIT 1
                        """,
                        (project_code, service_type, business_type),
                    ).fetchone()
                if not row and project_name:
                    row = conn.execute(
                        """
                        SELECT rules_json FROM project_rule_center
                        WHERE project_name=? AND service_type=? AND IFNULL(business_type,'')=IFNULL(?, '') AND status IN ('已确认','待确认')
                        ORDER BY CASE status WHEN '已确认' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                        LIMIT 1
                        """,
                        (project_name, service_type, business_type),
                    ).fetchone()
                if row:
                    break
            if not row and project_code:
                row = conn.execute(
                    """
                    SELECT rules_json FROM project_rule_center
                    WHERE project_code=? AND service_type=? AND status IN ('已确认','待确认')
                    ORDER BY CASE status WHEN '已确认' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (project_code, service_type),
                ).fetchone()
            if not row and project_name:
                row = conn.execute(
                    """
                    SELECT rules_json FROM project_rule_center
                    WHERE project_name=? AND service_type=? AND status IN ('已确认','待确认')
                    ORDER BY CASE status WHEN '已确认' THEN 0 ELSE 1 END, updated_at DESC, id DESC
                    LIMIT 1
                    """,
                    (project_name, service_type),
                ).fetchone()

            # 如果 project_rule_center 没有规则，从 project_contracts（合同解析的规则）读取
            if not row and project_name:
                for business_type in business_types or [""]:
                    row = conn.execute(
                        """
                        SELECT rules_json FROM project_contracts
                        WHERE project_name=? AND service_type=? AND business_type=? AND status='active' AND is_active=1
                        ORDER BY id DESC LIMIT 1
                        """,
                        (project_name, service_type, business_type),
                    ).fetchone()
                    if row:
                        break
                if not row:
                    row = conn.execute(
                        """
                        SELECT rules_json FROM project_contracts
                        WHERE project_name=? AND service_type=? AND status='active' AND is_active=1
                        ORDER BY id DESC LIMIT 1
                        """,
                        (project_name, service_type),
                    ).fetchone()

            if row:
                rules = json_loads(row["rules_json"], {})
                for key, value in rules.items():
                    if value not in ("", None):
                        service_configs[key] = value
                # 合同中的 contract_deduction_coefficient 映射为 attendance_deduction_coefficient
                if "contract_deduction_coefficient" in rules and rules["contract_deduction_coefficient"] not in ("", None):
                    service_configs["attendance_deduction_coefficient"] = float(rules["contract_deduction_coefficient"])

                # 如果 rule_center 匹配到但缺少系数，回退到 project_contracts 补充
                if not service_configs.get("attendance_deduction_coefficient"):
                    contract_row = None
                    for bt in business_types or [""]:
                        contract_row = conn.execute(
                            """
                            SELECT rules_json FROM project_contracts
                            WHERE project_name=? AND service_type=? AND business_type=? AND status='active' AND is_active=1
                            ORDER BY id DESC LIMIT 1
                            """,
                            (project_name, service_type, bt),
                        ).fetchone()
                        if contract_row:
                            break
                    if not contract_row and project_name:
                        contract_row = conn.execute(
                            """
                            SELECT rules_json FROM project_contracts
                            WHERE project_name=? AND service_type=? AND status='active' AND is_active=1
                            ORDER BY id DESC LIMIT 1
                            """,
                            (project_name, service_type),
                        ).fetchone()
                    if contract_row:
                        contract_rules = json_loads(contract_row["rules_json"], {})
                        coeff = contract_rules.get("contract_deduction_coefficient")
                        if coeff not in ("", None):
                            service_configs["attendance_deduction_coefficient"] = float(coeff)
                        # 补充 rule_center 中缺失的其他字段
                        for key, value in contract_rules.items():
                            if key not in rules and value not in ("", None):
                                service_configs[key] = value

            configs_by_service[service_type] = service_configs
            # 保洁规则写入顶层configs保持兼容（保洁是主要服务类型）
            if service_type == "保洁":
                updated = service_configs

    # 把 configs_by_service 存到 updated 的特殊key中，供 audit_attendance 使用
    updated["_configs_by_service"] = configs_by_service
    return updated

def infer_service_types_from_business(audit_business_types: list[str]) -> list[str]:
    # 现阶段BI业态主要区分商场/住宅/外场；保安、保洁合同均可进入Rule Center。
    # 若未能识别服务类型，优先使用保洁规则，保持与现有系统兼容。
    return ["保洁", "保安"]

def pick(row: dict, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row and row[name] not in ("", None):
            return row[name]
    return default

def safe_float(value: Any, default: float = 0.0) -> float:
    """安全提取float：支持纯数字、'22元/小时'、'1.2'等混合文本。"""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        text = str(value)
        match = re.search(r'(\d+\.?\d*)', text)
        if match:
            return float(match.group(1))
        return default

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
    """计算下一天的日期字符串"""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        return date_str

def is_cross_midnight_shift(shift: dict) -> bool:
    """判断班次是否跨天（夜班）：结束时间 <= 开始时间"""
    start = parse_time_value(shift.get("start_time", "08:00"))
    end = parse_time_value(shift.get("end_time", "17:00"))
    if not start or not end:
        return False
    return time_to_minutes(end) <= time_to_minutes(start)

def shift_clock_minutes(clock_times: list[str], shift: dict) -> list[int]:
    """将打卡时间转为分钟数，处理跨天班次。
    对于跨天班次（如22:00-06:00），次日凌晨的打卡时间会+1440，
    使其在班次开始时间之后，从而正确计算迟到/早退/工时。
    """
    start = parse_time_value(shift.get("start_time", "08:00"))
    end = parse_time_value(shift.get("end_time", "17:00"))
    if not start:
        return []
    start_min = time_to_minutes(start)
    end_min = time_to_minutes(end) if end else start_min + 480
    cross_midnight = end_min <= start_min
    result = []
    for t in clock_times:
        p = parse_time_value(t)
        if not p:
            continue
        m = time_to_minutes(p)
        # 跨天班次：凌晨到下班后2小时内的打卡视为次日，+1440
        if cross_midnight and m < start_min and m <= end_min + 120:
            m += 1440
        result.append(m)
    return sorted(result)

def normalize_employee_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^\d+", "", text)
    text = re.sub(r"^[A-Za-z]+", "", text)
    text = text.translate(str.maketrans({
        "俠": "侠",
        "俥": "车",
        "麗": "丽",
        "鳳": "凤",
        "蘭": "兰",
        "劉": "刘",
        "張": "张",
        "陳": "陈",
        "趙": "赵",
        "黃": "黄",
        "峰": "丰",
        "颖": "影",
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
    """模糊匹配名字：当完全匹配失败时，尝试找到编辑距离为1的候选名。"""
    for name in candidates:
        if len(name) != len(target):
            continue
        if _levenshtein_distance(target, name) == 1:
            return name
    return None

def normalize_position_name(name: str) -> str:
    """归一化岗位名：去掉时长后缀（如'7h'、'8h'）、去空格。
    '楼栋保洁7h' → '楼栋保洁'
    '保洁领班7h' → '保洁领班'
    '领班' → '领班'
    """
    return re.sub(r'\d+\.?\d*\s*h?', '', str(name or '')).strip()

def normalize_contracts(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        position = str(pick(row, ["岗位", "岗位名称"])).strip()
        if not position:
            continue
        result.append({
            "position": position,
            "position_normalized": normalize_position_name(position),
            "business_type": str(pick(row, ["业态", "业务类型"], "")).strip(),
            "area": pick(row, ["区域", "服务区域"], ""),
            "contract_headcount": int(safe_float(pick(row, ["合同人数", "编制人数"], 0))),
            "staff_names": pick(row, ["编制人员", "人员"], ""),
            "hourly_rate": safe_float(pick(row, ["工时单价", "单价"], 0)),
            "service_type": pick(row, ["服务类型", "业态"], "保洁"),
        })
    return result

def normalize_schedules(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        employee = normalize_employee_name(pick(row, ["姓名", "人员姓名", "员工姓名"]))
        position = str(pick(row, ["岗位", "岗位名称"])).strip()
        date_value = pick(row, ["日期", "排班日期", "工作日期"])
        if not employee or not position or not date_value:
            continue
        result.append({
            "work_date": normalize_date(date_value),
            "position": position,
            "business_type": extract_business_from_remark(row),
            "area": pick(row, ["区域", "服务区域"], ""),
            "employee_name": employee,
            "shift_name": str(pick(row, ["班次", "班次名称"], "")).strip(),
            "schedule_type": pick(row, ["排班类型", "调整类型"], "正常"),
            "original_position": pick(row, ["原岗位"], ""),
            "original_employee_name": pick(row, ["原人员"], ""),
            "remark": pick(row, ["备注"], ""),
            "source_row_no": row.get("_source_row_no"),
        })
    return result

def extract_business_from_remark(row: dict) -> str:
    value = str(pick(row, ["业态", "业务类型"], "")).strip()
    if value:
        return value
    remark = str(pick(row, ["备注"], "")).strip()
    if "业态：" in remark:
        return remark.split("业态：", 1)[1].split()[0].strip()
    return ""

def normalize_shifts(rows: list[dict]) -> dict:
    result = {}
    for row in rows:
        name = str(pick(row, ["班次名称", "班次"])).strip()
        if not name:
            continue
        # 优先从班次名称中提取工时（如"经理岗10h"→10），其次用编制表工时字段
        name_hours = extract_hours_from_shift_name(name)
        standard_hours = name_hours if name_hours is not None else safe_float(pick(row, ["工时", "标准工时"], 8), 8.0)
        # 打卡次数：优先取合同编制表中的值，为空时根据工时动态判断（≤4h打2次，>4h打3次）
        clock_count_raw = pick(row, ["要求打卡次数", "打卡次数"], "")
        if clock_count_raw and str(clock_count_raw).strip():
            required_clock_count = int(safe_float(clock_count_raw, 2.0))
        else:
            required_clock_count = clock_count_for_hours(standard_hours)
        result[name] = {
            "shift_name": name,
            "start_time": pick(row, ["上班时间", "开始时间"], ""),
            "end_time": pick(row, ["下班时间", "结束时间"], ""),
            "standard_hours": standard_hours,
            "required_clock_count": required_clock_count,
            "clock_window": pick(row, ["允许打卡窗口", "打卡窗口"], ""),
        }
    return result

def extract_hours_from_shift_name(name: str) -> float | None:
    """从班次名称中提取工时，如'经理岗10h'→10.0, '夜班PA7.5h'→7.5"""
    match = re.search(r"(\d+(?:\.\d+)?)\s*h", name, re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None

def clock_count_for_hours(hours: float) -> int:
    """根据工时动态确定打卡次数：4小时及以下打2次卡，超过4小时打3次卡。"""
    if hours <= 4:
        return 2
    return 3

def normalize_attendance(rows: list[dict]) -> list[dict]:
    grouped = defaultdict(lambda: {"times": [], "remarks": []})
    for row in rows:
        employee = normalize_employee_name(pick(row, ["姓名", "人员姓名", "员工姓名"]))
        date_value = pick(row, ["日期", "考勤日期", "工作日期", "打卡日期"])
        if not employee or not date_value:
            continue
        work_date = normalize_date(date_value)
        clock_text = pick(row, ["打卡时间", "打卡记录", "打卡", "考勤时间"], "")
        times = extract_clock_times(clock_text)
        if not times:
            single = parse_time_value(clock_text)
            if single:
                times = [single.strftime("%H:%M")]
        grouped[(employee, work_date)]["times"].extend(times)
        proof_text = " ".join(
            str(pick(row, keys, "") or "")
            for keys in [
                ["备注"],
                ["说明"],
                ["原因"],
                ["补卡说明", "补卡原因", "补卡"],
                ["审批状态", "审批结果"],
                ["证明", "出勤证明", "凭证"],
            ]
        ).strip()
        if proof_text:
            grouped[(employee, work_date)]["remarks"].append(proof_text)
    result = []
    for (employee, work_date), payload in grouped.items():
        unique_times = sorted(set(payload["times"]))
        result.append({
            "employee_name": employee,
            "work_date": work_date,
            "clock_times": unique_times,
            "remark": "；".join(dict.fromkeys(item for item in payload["remarks"] if item)),
        })
    return result

def infer_audit_business_types(attendance_rows: list[dict]) -> list[str]:
    values = []
    for row in attendance_rows:
        value = str(pick(row, ["业态", "业务类型"], "")).strip()
        if value:
            values.append(normalize_business_type(value))
    return sorted(set(v for v in values if v))

def normalize_business_type(value: str) -> str:
    text = str(value or "")
    if "商酒" in text:
        return "商业"
    if "住宅" in text:
        return "住宅"
    if "写字楼" in text or "办公" in text:
        return "写字楼"
    if "酒店" in text:
        return "酒店"
    if "街区" in text or "外场" in text or "外围" in text or "停车场" in text or "物业" in text:
        return "街区"
    if text.strip() == "商" or "商场" in text or "商业" in text or "内场" in text:
        return "商业"
    if text.strip() == "住":
        return "住宅"
    return text.strip()

def business_matches(source: str, target: str) -> bool:
    source_norm = normalize_business_type(source)
    target_norm = normalize_business_type(target)
    if not source_norm or not target_norm:
        return False
    return source_norm == target_norm

def filter_scope_by_business_type(contracts: list[dict], schedules: list[dict], audit_business_types: list[str]):
    if not audit_business_types:
        return contracts, schedules
    # 如果BI数据中存在未确定业态，说明BI路径解析不完整，不过滤
    if "未确定" in audit_business_types:
        return contracts, schedules
    filtered_contracts = [
        item for item in contracts
        if any(business_matches(item_scope_text(item), business_type) for business_type in audit_business_types)
    ]
    filtered_schedules = [
        item for item in schedules
        if any(business_matches(item_scope_text(item), business_type) for business_type in audit_business_types)
    ]
    return filtered_contracts, filtered_schedules

def item_scope_text(item: dict) -> str:
    return " ".join(
        str(item.get(key, ""))
        for key in ["business_type", "remark", "area", "position", "service_type"]
    )

def align_schedule_month_to_selected_month(schedules: list[dict], audit_month: str) -> list[dict]:
    month = normalize_month_text(audit_month)
    if not schedules or not month:
        return schedules
    aligned = []
    for item in schedules:
        copied = dict(item)
        if copied.get("work_date") and len(copied["work_date"]) >= 10:
            copied["work_date"] = month + copied["work_date"][7:]
        aligned.append(copied)
    return aligned

def normalize_month_text(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"(20\d{2})[-年/]?(\d{1,2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"

def extract_clock_times(value: Any) -> list[str]:
    text = str(value or "")
    for sep in [";", "；", ",", "，", "\n", "、", "|"]:
        text = text.replace(sep, " ")
    times = []
    for part in text.split():
        parsed = parse_time_value(part)
        if parsed:
            times.append(parsed.strftime("%H:%M"))
    return times

def build_schedule_audit_summary(details):
    grouped = {}
    for detail in details:
        key = (detail.get("work_date", ""), detail.get("position", ""), detail.get("area", ""))
        item = grouped.setdefault(key, {
            "work_date": detail.get("work_date", ""),
            "position": detail.get("position", ""),
            "area": detail.get("area", ""),
            "contract_headcount": 0,
            "scheduled_headcount": 0,
            "actual_attendance_count": 0,
            "shortage_count": 0,
            "shortage_hours": 0,
            "hourly_rate": 0,
            "position_deduction_amount": 0,
            "result_status": "正常",
            "calculation_detail": "以月度排班表为唯一审核依据；合同编制表不参与审核计算。",
        })
        item["scheduled_headcount"] += 1
        if detail.get("clock_times"):
            item["actual_attendance_count"] += 1
        if detail.get("result_status") == "异常":
            item["result_status"] = "存在异常"
    return sorted(grouped.values(), key=lambda row: (row["work_date"], row["position"], row["area"]))

def has_valid_attendance_proof(record: dict) -> bool:
    text = str(record.get("remark") or "")
    if not text:
        return False
    proof_keywords = ["出勤证明", "有效证明", "证明", "凭证", "补卡", "补签", "审批通过", "已审批", "已通过"]
    reject_keywords = ["驳回", "拒绝", "未通过", "无证明", "未提供", "无凭证"]
    return any(keyword in text for keyword in proof_keywords) and not any(keyword in text for keyword in reject_keywords)

def resolve_shift(schedule: dict, shifts: dict) -> dict:
    shift_name = str(schedule.get("shift_name") or "").strip()
    position_name = str(schedule.get("position") or "").strip()
    matched = None
    if shift_name in shifts:
        matched = shifts[shift_name]
    else:
        # 大小写不敏感匹配
        shift_name_lower = shift_name.lower()
        for key, val in shifts.items():
            if key.lower() == shift_name_lower:
                matched = val
                break
    if not matched:
        # 归一化匹配：去掉时长后缀后匹配
        norm_name = normalize_position_name(shift_name)
        if norm_name and norm_name in shifts:
            matched = shifts[norm_name]
    if not matched:
        # 归一化后大小写不敏感包含匹配
        norm_name = normalize_position_name(shift_name)
        norm_name_lower = norm_name.lower() if norm_name else ""
        for key, val in shifts.items():
            norm_key = normalize_position_name(key)
            if norm_name_lower and norm_key and (norm_name_lower in norm_key.lower() or norm_key.lower() in norm_name_lower):
                matched = val
                break
    # 第二优先：班次名匹配不到时，用排班岗位名匹配合同编制表生成的班次标准
    if not matched and position_name:
        if position_name in shifts:
            matched = shifts[position_name]
        else:
            pos_lower = position_name.lower()
            for key, val in shifts.items():
                if key.lower() == pos_lower:
                    matched = val
                    break
        if not matched:
            norm_pos = normalize_position_name(position_name)
            if norm_pos and norm_pos in shifts:
                matched = shifts[norm_pos]
        if not matched:
            norm_pos = normalize_position_name(position_name)
            norm_pos_lower = norm_pos.lower() if norm_pos else ""
            for key, val in shifts.items():
                norm_key = normalize_position_name(key)
                if norm_pos_lower and norm_key and (norm_pos_lower in norm_key.lower() or norm_key.lower() in norm_pos_lower):
                    matched = val
                    break
    # 如果匹配到的班次有有效时间，直接返回
    if matched and matched.get("start_time") and matched.get("end_time"):
        return matched
    # 匹配到的班次没有时间，保留其工时和打卡次数信息，继续尝试提取时间
    base_hours = float(matched.get("standard_hours", 8) or 8) if matched else 8.0
    base_clock_count = matched.get("required_clock_count") if matched else None
    base_clock_window = matched.get("clock_window", "") if matched else ""
    # 尝试从班次名中提取时间（如"07:00-19:00"）
    start, end = parse_shift_time_text(shift_name)
    if start and end:
        name_hours = extract_hours_from_shift_name(shift_name)
        standard_hours = name_hours if name_hours is not None else calc_standard_hours(start, end)
        return {
            "shift_name": shift_name,
            "start_time": start,
            "end_time": end,
            "standard_hours": standard_hours,
            "required_clock_count": base_clock_count or clock_count_for_hours(standard_hours),
            "clock_window": base_clock_window,
        }
    # 尝试从班次名中提取工时（如"垃圾房岗7h"→7h）
    name_hours = extract_hours_from_shift_name(shift_name)
    if name_hours is not None:
        end_hour = int(name_hours) + 8
        return {
            "shift_name": shift_name,
            "start_time": "08:00",
            "end_time": f"{end_hour:02d}:00",
            "standard_hours": name_hours,
            "required_clock_count": base_clock_count or clock_count_for_hours(name_hours),
            "clock_window": base_clock_window,
        }
    # 最终兜底：使用默认时间，保留匹配到的工时信息
    return {
        "shift_name": shift_name,
        "start_time": "08:00",
        "end_time": "17:00",
        "standard_hours": base_hours,
        "required_clock_count": base_clock_count or clock_count_for_hours(base_hours),
        "clock_window": base_clock_window,
    }

def parse_shift_time_text(value: Any) -> tuple[str, str]:
    text = str(value or "").replace("：", ":").strip()
    match = re.search(r"(\d{1,2}:\d{2})\s*[-~—至到]\s*(\d{1,2}:\d{2})", text)
    if not match:
        return "", ""
    return match.group(1), match.group(2)

def calc_standard_hours(start: str, end: str) -> float:
    start_time = parse_time_value(start)
    end_time = parse_time_value(end)
    if not start_time or not end_time:
        return 8.0
    minutes = time_to_minutes(end_time) - time_to_minutes(start_time)
    if minutes < 0:
        minutes += 24 * 60
    return round(minutes / 60, 2)

def infer_service_type_from_position(position: str) -> str:
    """从岗位名推断服务类型（保安/保洁）。"""
    pos = str(position or "")
    if "保安" in pos or "秩序" in pos or "门岗" in pos or "巡逻" in pos or "监控" in pos:
        return "保安"
    return "保洁"

def audit_attendance(batch_id: int, schedules, shifts, attendance_by_person_date, attendance_by_date, contracts, configs):
    # 提取按服务类型区分的规则（保安/保洁各自独立的扣款规则）
    configs_by_service = configs.pop("_configs_by_service", {}) if isinstance(configs, dict) else {}
    def get_configs_for_position(position: str) -> dict:
        """根据岗位推断服务类型，返回对应的合同规则。无匹配时回退到顶层configs。"""
        st = infer_service_type_from_position(position)
        if st in configs_by_service:
            sc = configs_by_service[st]
            # 确保有必需字段，否则回退到顶层
            if sc.get("late_early_tiers") and sc.get("attendance_deduction_coefficient"):
                return sc
        return configs

    # 构建岗位→时薪映射，支持归一化匹配（去掉"7h"等时长后缀）
    hourly_rate_by_position = {}
    hourly_rate_by_normalized = {}
    for c in contracts:
        pos = c["position"]
        rate = c["hourly_rate"]
        hourly_rate_by_position[pos] = rate
        norm = normalize_position_name(pos)
        if norm and norm not in hourly_rate_by_normalized:
            hourly_rate_by_normalized[norm] = rate
    def get_hourly_rate(position):
        if position in hourly_rate_by_position:
            return hourly_rate_by_position[position]
        norm = normalize_position_name(position)
        if norm in hourly_rate_by_normalized:
            return hourly_rate_by_normalized[norm]
        # 模糊匹配：归一化后的岗位名包含关系
        for key, rate in hourly_rate_by_normalized.items():
            if norm and key and (norm in key or key in norm):
                return rate
        return 0
    details = []
    deductions = []
    missing_clock_counter = defaultdict(int)

    # 预计算所有考勤人员名，用于模糊匹配
    att_names = set(name for (name, _) in attendance_by_person_date.keys())
    # 预计算排班中未匹配的人员名 -> 模糊匹配结果
    sched_names = set(s["employee_name"] for s in schedules)
    fuzzy_map = {}
    for sname in sched_names:
        if sname not in att_names:
            matched = fuzzy_match_name(sname, att_names)
            if matched:
                fuzzy_map[sname] = matched

    for schedule in sorted(schedules, key=lambda item: (item.get("employee_name", ""), item.get("work_date", ""))):
        work_date = schedule["work_date"]
        employee = schedule["employee_name"]
        shift = resolve_shift(schedule, shifts)
        record = attendance_by_person_date.get((employee, work_date))
        if record is None and employee in fuzzy_map:
            # 模糊匹配回退：用相似名字的考勤记录
            record = attendance_by_person_date.get((fuzzy_map[employee], work_date))
        if record is None:
            record = {"clock_times": []}
        clock_times = list(record.get("clock_times", []))
        # 夜班跨天：合并次日凌晨的打卡记录（如22:00-06:00班次，次日0:00-08:00的打卡）
        if is_cross_midnight_shift(shift):
            end_t = parse_time_value(shift.get("end_time", "06:00"))
            end_buffer = (time_to_minutes(end_t) + 120) if end_t else 480
            next_date = get_next_date(work_date)
            next_record = attendance_by_person_date.get((employee, next_date))
            if next_record is None and employee in fuzzy_map:
                next_record = attendance_by_person_date.get((fuzzy_map[employee], next_date))
            if next_record:
                next_times = [
                    t for t in next_record.get("clock_times", [])
                    if parse_time_value(t) and time_to_minutes(parse_time_value(t)) <= end_buffer
                ]
                if next_times:
                    clock_times = sorted(set(clock_times + next_times))
                    merged_remark = next_record.get("remark", "")
                    if merged_remark:
                        existing = record.get("remark", "")
                        record = {**record, "clock_times": clock_times, "remark": f"{existing}；{merged_remark}" if existing else merged_remark}
                    else:
                        record = {**record, "clock_times": clock_times}
        exceptions = []
        exception_reasons = []
        deduction_items = []
        standard_hours = float(shift.get("standard_hours", 8) or 8)
        # 按岗位推断服务类型，获取对应的合同规则（保安/保洁规则独立）
        pos_configs = get_configs_for_position(schedule["position"])
        # 合同8.6条：每人每日进行不低于早、中、晚三次脸部识别打卡
        # 不仅要看打卡次数，还要看是否覆盖早、中、晚三个时段
        # 打卡次数优先级：短工时(≤4h)岗位打2次 > 合同约定的打卡次数 > 工时动态判断 > 默认3次
        if standard_hours <= 4:
            required_count = 2
        else:
            contract_clock_count = pos_configs.get("required_clock_count") or configs.get("required_clock_count")
            if contract_clock_count:
                required_count = int(contract_clock_count)
            else:
                required_count = clock_count_for_hours(standard_hours)
        actual_hours = calc_work_hours(clock_times, shift)
        deduction_coeff = float(pos_configs.get("attendance_deduction_coefficient") or configs.get("attendance_deduction_coefficient", 1.2))
        # 判断打卡时段覆盖情况（仅当要求3次及以上打卡时才检查时段覆盖）
        if required_count >= 3:
            missing_periods = check_missing_clock_periods(clock_times, shift)
        else:
            missing_periods = []

        if not clock_times:
            exceptions.append("缺勤")
            other_people = [
                item.get("employee_name", "")
                for item in attendance_by_date.get(work_date, [])
                if item.get("employee_name") and item.get("employee_name") != employee
            ]
            if other_people:
                exceptions.append("排班与实际出勤不一致")
                exception_reasons.append("排班与实际出勤不一致，请项目核实排班。系统不会自动判定顶岗、调岗、换班或调休。")
            amount = round(standard_hours * get_hourly_rate(schedule["position"]) * deduction_coeff, 2)
            deduction_items.append(("缺勤", amount, f"{standard_hours} × {get_hourly_rate(schedule['position'])} × {deduction_coeff}"))
        elif len(clock_times) < required_count or missing_periods:
            # 打卡次数不足 或 打卡时段未覆盖早中晚：只按漏打卡处理，不再同时算缺勤/工时不足
            # 合同约定每人每月有3次补卡机会，提供出勤证明即可免扣
            # 漏打卡是对"未按规定打卡"的处罚，与是否实际缺勤无关，一天只扣一次
            exceptions.append("疑似漏打卡")
            missing_count_this = required_count - len(clock_times)
            if missing_periods and missing_count_this <= 0:
                missing_count_this = len(missing_periods)
            month_key = (employee, work_date[:7])
            missing_clock_counter[month_key] += 1
            free_times = int(float(pos_configs.get("missing_clock_free_times_per_month", configs.get("missing_clock_free_times_per_month", 0)) or 0))
            proof_required = bool(pos_configs.get("missing_clock_free_requires_attendance_proof", configs.get("missing_clock_free_requires_attendance_proof")))
            has_proof = has_valid_attendance_proof(record)
            period_desc = f"缺少{','.join(missing_periods)}时段打卡" if missing_periods else f"缺{missing_count_this}次打卡"
            exception_reasons.append(
                f"每日要求{required_count}次打卡（覆盖上班、中间、下班时段），实际{len(clock_times)}次（{period_desc}）。"
                f"合同约定月累计漏打卡前{free_times}次需提交有效出勤证明免扣，超过{free_times}次扣{pos_configs.get('missing_clock_deduction', configs.get('missing_clock_deduction', 50))}元/人次。"
                f"已有打卡记录：{'、'.join(clock_times)}"
            )
            clock_deduction = round(float(pos_configs.get("missing_clock_deduction", configs.get("missing_clock_deduction", 50))), 2)
            if has_proof:
                deduction_items.append(("漏打卡", 0, f"疑似漏打卡，月累计第{missing_clock_counter[month_key]}次，已提供出勤证明，免扣款"))
            else:
                deduction_items.append(("漏打卡", clock_deduction, f"疑似漏打卡，月累计第{missing_clock_counter[month_key]}次，扣款{clock_deduction}元。如提供出勤证明可免扣"))
        elif check_abnormal_clock_time(clock_times, shift):
            # 三次打卡且时段全覆盖，但早上打卡时间过早：标注"打卡时间异常"
            exceptions.append("打卡时间异常")
            abnormal_detail = check_abnormal_clock_time(clock_times, shift)
            exception_reasons.append(
                f"打卡次数{len(clock_times)}次已达标，但{abnormal_detail}。"
                f"已有打卡记录：{'、'.join(clock_times)}，请项目核实打卡数据是否准确"
            )
        else:
            late_minutes = calc_late_minutes(clock_times, shift, pos_configs)
            early_minutes = calc_early_minutes(clock_times, shift, pos_configs)
            # 根据合同8.6条：早退/迟到>60分钟按缺勤处理，不再叠加"工时不足"扣款
            late_converted_to_absence = False
            early_converted_to_absence = False
            over_minutes_threshold = float(pos_configs.get("late_early_over_minutes_as_absence", configs.get("late_early_over_minutes_as_absence", 60)) or 60)
            if late_minutes > 0:
                exceptions.append("迟到")
                amount, calc = calc_late_early_amount(late_minutes, standard_hours, get_hourly_rate(schedule["position"]), pos_configs)
                deduction_items.append(("迟到", amount, calc))
                if late_minutes > over_minutes_threshold:
                    late_converted_to_absence = True
            if early_minutes > 0:
                exceptions.append("早退")
                amount, calc = calc_late_early_amount(early_minutes, standard_hours, get_hourly_rate(schedule["position"]), pos_configs)
                deduction_items.append(("早退", amount, calc))
                if early_minutes > over_minutes_threshold:
                    early_converted_to_absence = True
            # 工时不足扣款：仅当迟到/早退未转为缺勤时才计算（合同8.6条阶梯规则，避免重复扣款）
            if actual_hours < standard_hours * pos_configs.get("minimum_work_hour_ratio", configs.get("minimum_work_hour_ratio", 0.9)):
                if late_converted_to_absence or early_converted_to_absence:
                    # 迟到/早退已按缺勤处理，工时不足不再重复扣款
                    exception_reasons.append(f"实际工时{actual_hours}h低于标准{standard_hours}h的{int(pos_configs.get('minimum_work_hour_ratio', configs.get('minimum_work_hour_ratio', 0.9))*100)}%，因早退/迟到已超{int(over_minutes_threshold)}分钟按缺勤处理，工时不足不再重复扣款")
                else:
                    shortage_hours = max(standard_hours - actual_hours, 0)
                    exceptions.append("工时不足")
                    amount = round(shortage_hours * get_hourly_rate(schedule["position"]) * deduction_coeff, 2)
                    deduction_items.append(("工时不足", amount, f"{shortage_hours} × {get_hourly_rate(schedule['position'])} × {deduction_coeff}"))

        unique_exceptions = list(dict.fromkeys(exceptions))
        raw_total = sum(i[1] for i in deduction_items)
        # 第一版不生成扣款金额，只显示异常数据让项目确认
        capped_total = 0
        detail = {
            **schedule,
            "clock_times": "、".join(clock_times),
            "shift_start_time": str(shift.get("start_time", "")),
            "shift_end_time": str(shift.get("end_time", "")),
            "shift_hours": standard_hours,
            "actual_hours": actual_hours,
            "exception_type": "、".join(unique_exceptions) if unique_exceptions else "正常",
            "exception_reason": "；".join(dict.fromkeys(exception_reasons)) if exception_reasons else ("无异常" if not unique_exceptions else "按月度排班表与BI打卡记录审核"),
            "deduction_amount": round(capped_total, 2),
            "result_status": "异常" if unique_exceptions else "正常",
        }
        details.append(detail)
        for exception_type, amount, calc in deduction_items:
            deductions.append({
                "work_date": work_date,
                "employee_name": employee,
                "position": schedule["position"],
                "exception_type": exception_type,
                "deduction_rule": exception_type,
                "deduction_amount": 0,  # 第一版不生成扣款金额
                "calculation_detail": calc,
                "is_included_total": False,
            })
        log(batch_id, "employee", employee, "人员考勤审核", "attendance_audit", {"schedule": schedule, "clock_times": clock_times}, detail, detail["exception_type"])
    return details, deductions

def calc_work_hours(clock_times: list[str], shift: dict | None = None) -> float:
    if shift:
        mins = shift_clock_minutes(clock_times, shift)
        if len(mins) < 2:
            return 0.0
        return round((max(mins) - min(mins)) / 60, 2)
    parsed = [parse_time_value(t) for t in clock_times]
    parsed = [p for p in parsed if p]
    if len(parsed) < 2:
        return 0.0
    minutes = time_to_minutes(max(parsed)) - time_to_minutes(min(parsed))
    if minutes < 0:
        minutes += 24 * 60
    return round(minutes / 60, 2)

def check_missing_clock_periods(clock_times: list[str], shift: dict) -> list[str]:
    """检查打卡记录是否覆盖班次的上班、中间、下班三个时段。
    时段窗口根据班次实际时间动态计算，支持白班和夜班（跨天）。
    - 白班（如08:00-17:00）：上班段、中间段、下班段分别对应早中晚
    - 夜班（如22:00-06:00）：上班段（班次开始前后）、中间段（班次中段）、下班段（班次结束前后）
    """
    if not clock_times:
        return []
    rel_clock = shift_clock_minutes(clock_times, shift)
    if not rel_clock:
        return []
    start = parse_time_value(shift.get("start_time", "08:00"))
    end = parse_time_value(shift.get("end_time", "17:00"))
    if not start or not end:
        return []
    start_min = time_to_minutes(start)
    end_min = time_to_minutes(end)
    cross_midnight = end_min <= start_min
    duration = (end_min + 1440 - start_min) if cross_midnight else (end_min - start_min)
    # 三个时段窗口（基于班次的绝对分钟数）：
    # 上班段：班次开始前2小时到开始后2小时
    period1_start = start_min - 120
    period1_end = start_min + 120
    # 中间段：班次1/3到2/3处，各扩展1.5小时
    mid1 = start_min + duration / 3
    mid2 = start_min + duration * 2 / 3
    period2_start = mid1 - 90
    period2_end = mid2 + 90
    # 下班段：班次结束前2小时到结束后2小时
    end_abs = start_min + duration
    period3_start = end_abs - 120
    period3_end = end_abs + 120
    has_period1 = any(period1_start <= r <= period1_end for r in rel_clock)
    has_period2 = any(period2_start <= r <= period2_end for r in rel_clock)
    has_period3 = any(period3_start <= r <= period3_end for r in rel_clock)
    missing = []
    if not has_period1:
        missing.append("上班")
    if not has_period2:
        missing.append("中间")
    if not has_period3:
        missing.append("下班")
    return missing

def check_abnormal_clock_time(clock_times: list[str], shift: dict) -> str | None:
    """检查三次打卡且时段全覆盖时，最早打卡时间是否过早。
    如果最早打卡时间比班次开始时间早超过1小时，返回异常描述；否则返回None。
    支持夜班跨天：用归一化后的打卡时间比较。
    """
    if not clock_times or not shift:
        return None
    start = parse_time_value(shift.get("start_time", "08:00"))
    if not start:
        return None
    start_min = time_to_minutes(start)
    # 用归一化分钟数排序找到最早的打卡
    time_norm_pairs = []
    for t in clock_times:
        single_mins = shift_clock_minutes([t], shift)
        if single_mins:
            time_norm_pairs.append((t, single_mins[0]))
    if not time_norm_pairs:
        return None
    time_norm_pairs.sort(key=lambda x: x[1])
    earliest_time, earliest_min = time_norm_pairs[0]
    diff = start_min - earliest_min
    if diff > 120:
        hours = int(diff // 60)
        mins_part = int(diff % 60)
        return f"最早打卡时间{earliest_time}比班次开始时间{shift.get('start_time','')}早{hours}小时{mins_part}分钟"
    return None

def calc_late_minutes(clock_times, shift, configs) -> int:
    if not clock_times or not shift:
        return 0
    start = parse_time_value(shift.get("start_time"))
    if not start:
        return 0
    start_min = time_to_minutes(start)
    mins = shift_clock_minutes(clock_times, shift)
    if not mins:
        return 0
    first_min = mins[0]
    return max(first_min - start_min - int(configs["late_grace_minutes"]), 0)

def calc_early_minutes(clock_times, shift, configs) -> int:
    if not clock_times or not shift:
        return 0
    end = parse_time_value(shift.get("end_time"))
    if not end:
        return 0
    start = parse_time_value(shift.get("start_time"))
    start_min = time_to_minutes(start) if start else 0
    end_min = time_to_minutes(end)
    cross_midnight = end_min <= start_min
    actual_end = end_min + 1440 if cross_midnight else end_min
    mins = shift_clock_minutes(clock_times, shift)
    if not mins:
        return 0
    last_min = mins[-1]
    return max(actual_end - last_min - int(configs["early_leave_grace_minutes"]), 0)

def calc_late_early_amount(minutes: int, standard_hours: float, hourly_rate: float, configs: dict) -> tuple[float, str]:
    tiers = configs.get("late_early_tiers")
    if isinstance(tiers, list) and tiers:
        for tier in sorted(tiers, key=lambda item: float(item.get("max_minutes", 0))):
            if minutes <= float(tier.get("max_minutes", 0)):
                amount = round(float(tier.get("amount", 0)), 2)
                return amount, f"{minutes}分钟，按合同分档≤{tier.get('max_minutes')}分钟，扣款{amount}元/次"
        over_minutes = float(configs.get("late_early_over_minutes_as_absence", 0) or 0)
        if over_minutes and minutes > over_minutes:
            coeff = float(configs["attendance_deduction_coefficient"])
            amount = round(standard_hours * hourly_rate * coeff, 2)
            return amount, f"{minutes}分钟超过{over_minutes}分钟，按缺勤处理：{standard_hours} × {hourly_rate} × {coeff}"
    # 合同未配置分档规则时不扣款（已在前置校验中拦截，此处为防御性代码）
    return 0, f"{minutes}分钟，合同未配置对应扣档规则"

def build_exception_statistics(details):
    people = {}
    for detail in details:
        employee = detail.get("employee_name", "")
        position = detail.get("position", "")
        if not employee:
            continue
        key = (employee, position)
        item = people.setdefault(key, {
            "employee_name": employee,
            "position": position,
            "total_days": 0,
            "exception_days": 0,
            "exception_count": 0,
            "late_count": 0,
            "early_leave_count": 0,
            "missing_clock_count": 0,
            "absence_count": 0,
            "insufficient_hours_count": 0,
            "deduction_amount": 0,
            "exception_types": Counter(),
        })
        item["total_days"] += 1
        exception_text = str(detail.get("exception_type", ""))
        if exception_text and exception_text != "正常":
            item["exception_days"] += 1
            # 只统计标准异常类型，描述性文字（如"排班与实际出勤不一致"）不计入异常次数
            standard_types = {"迟到", "早退", "漏打卡", "缺勤", "工时不足"}
            for name in exception_text.split("、"):
                if name in standard_types:
                    item["exception_count"] += 1
                    item["exception_types"][name] += 1
                    if name == "迟到":
                        item["late_count"] += 1
                    elif name == "早退":
                        item["early_leave_count"] += 1
                    elif name == "漏打卡":
                        item["missing_clock_count"] += 1
                    elif name == "缺勤":
                        item["absence_count"] += 1
                    elif name == "工时不足":
                        item["insufficient_hours_count"] += 1
            # 如果没有标准异常类型但有异常描述，至少计1次
            if item["exception_count"] == 0:
                item["exception_count"] = 1
                item["exception_types"][exception_text] += 1
            item["deduction_amount"] += float(detail.get("deduction_amount", 0) or 0)
    rows = []
    for item in people.values():
        if item["exception_count"] <= 0:
            continue
        exception_types = item.pop("exception_types")
        item["exception_type"] = "、".join(name for name, _ in exception_types.most_common())
        item["count"] = item["exception_count"]
        item["deduction_amount"] = round(item["deduction_amount"], 2)
        rows.append(item)
    return sorted(rows, key=lambda row: (row["deduction_amount"], row["exception_count"]), reverse=True)

def build_deduction_summary(position_results, attendance_deductions):
    attendance_amount = sum(float(i["deduction_amount"]) for i in attendance_deductions if i["is_included_total"])
    return [{
        "position_deduction_amount": 0,
        "attendance_deduction_amount": round(attendance_amount, 2),
        "total_deduction_amount": round(attendance_amount, 2),
    }]

def build_summary(position_results, details, deduction_summary):
    return {
        "audited_days": len(set(i["work_date"] for i in position_results)),
        "position_count": len(set(i["position"] for i in position_results)),
        "shortage_count": 0,
        "schedule_task_count": len(details),
        "exception_count": sum(1 for i in details if i["result_status"] == "异常"),
        "position_deduction_amount": deduction_summary[0]["position_deduction_amount"],
        "attendance_deduction_amount": deduction_summary[0]["attendance_deduction_amount"],
        "total_deduction_amount": deduction_summary[0]["total_deduction_amount"],
    }

def build_ai_analysis(summary, exceptions, deductions):
    exception_text = "、".join([f"{i['exception_type']}{i['count']}次" for i in exceptions]) or "暂无明显异常"
    return (
        f"本次审核以月度排班表为唯一审核依据，覆盖{summary['audited_days']}个日期、{summary['position_count']}类岗位、{summary.get('schedule_task_count', 0)}条排班任务。"
        f"BI考勤仅用于验证排班人员实际打卡，人员考勤异常合计{summary['exception_count']}人次，"
        f"异常结构为：{exception_text}。"
        f"合同编制表仅作为基础配置，不参与合同人数、缺编、履约率或岗位扣款计算。"
        f"本月人员考勤扣款{summary['attendance_deduction_amount']}元，合计扣款{summary['total_deduction_amount']}元。"
        f"如排班人员与BI实际打卡人员不一致，系统只提示项目核实排班，不自动判定顶岗、调岗、换班或调休。"
    )

def log(batch_id, scope_type, scope_name, step_name, rule_key, input_data, output_data, message):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO audit_logs(audit_batch_id,scope_type,scope_name,step_name,rule_key,input_json,output_json,message,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (batch_id, scope_type, scope_name, step_name, rule_key, json_dumps(input_data), json_dumps(output_data), message, now_text()),
        )
