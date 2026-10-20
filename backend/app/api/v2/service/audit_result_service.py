"""审核结果业务逻辑。"""
import json
import logging
import re
from calendar import monthrange
from datetime import datetime
from fastapi import HTTPException
from app.api.v2.core.constants import AuditStatus
from app.api.v2.core.database import json_dumps, now_text
from app.api.v2.core.result import Result
from app.api.v2.core.validators import require_service_type
from app.api.v2.dao import audit_result_dao, position_dao, bi_dao, contract_dao
from app.api.v2.models.audit_result_models import AuditResult
from app.api.v2.service.audit_slot_service import run_slot_audit
from app.api.v2.service.audit_attendance_service import (
    run_attendance_s04_audit,
    extract_s04_rules,
    get_absence_coefficient,
)
from app.api.v2.utils.audit_common import (
    normalize_employee_name,
    parse_position_shifts,
    get_shift_for_date,
    parse_time_value,
    time_to_minutes,
    confirm_key,
    mid_clock_confirm,
    is_charged,
    recompute_audit_totals,
    audit_totals_metrics,
)

logger = logging.getLogger(__name__)


def _load_active_s04_rules(project_name: str, business_type: str, service_type: str):
    """返回启用合同的 S04 规则（同项目同业态同服务类型多份合同时，取"最近更新"的那份）。

    用于：槽位缺编扣款系数、S04 考勤管理规则读取。
    系数来源统一为合同细则卡片里填的 contract_deduction_coefficient。
    """
    contract = contract_dao.get_latest_active_contract(
        project_name, business_type, service_type=service_type, require_rules=True
    )
    if contract is None:
        return None
    return extract_s04_rules(contract.rules)


def _next_month(audit_month: str) -> str:
    """计算下个月，保持输入格式（'YYYYMM' → 'YYYYMM'，'YYYY-MM' → 'YYYY-MM'）。"""
    s = str(audit_month or "").strip()
    m = re.match(r"(\d{4})[-年.]?(\d{1,2})", s)
    if not m:
        return ""
    year, month = int(m.group(1)), int(m.group(2))
    has_sep = bool(re.match(r"\d{4}[-年.]", s))
    if month == 12:
        nm = f"{year + 1:04d}-01" if has_sep else f"{year + 1:04d}01"
    else:
        nm = f"{year:04d}-{month + 1:02d}" if has_sep else f"{year:04d}{month + 1:02d}"
    return nm


def _find_cross_night_employees_on_last_day(
    position_infos: list,
    audit_month: str,
) -> set[str]:
    """找出当月最后一天有跨夜班次的员工姓名集合。"""
    m = re.match(r"(\d{4})[-年.]?(\d{1,2})", str(audit_month or "").strip())
    if not m:
        return set()
    year, month_num = int(m.group(1)), int(m.group(2))
    _, last_day = monthrange(year, month_num)
    # 标准化为 ISO 格式（如 "2026-08-31"），与排班表中的日期格式一致
    month_iso = f"{year:04d}-{month_num:02d}"
    last_day_date = f"{month_iso}-{last_day:02d}"

    employees: set[str] = set()
    for pi in position_infos:
        for p in pi.positions:
            shifts = parse_position_shifts(p.position_name, p.shift_time)
            for slot in p.slots:
                if last_day_date in slot.daily:
                    start, end = get_shift_for_date(shifts, last_day_date)
                    _s = time_to_minutes(parse_time_value(start))
                    _e = time_to_minutes(parse_time_value(end))
                    auto_cross = bool(_s is not None and _e is not None and _e <= _s)
                    if not auto_cross:
                        continue
                    for cells in slot.daily[last_day_date]:
                        for name in cells.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                employees.add(nn)
    return employees


def _merge_next_month_bi(
    current_records: list[dict],
    next_records: list[dict],
    audit_month: str,
    cross_night_employees: set[str],
) -> list[dict]:
    """将下个月1号的 BI 打卡数据以独立 ISO 日期标签合并到当月记录中。

    仅对 cross_night_employees 中的员工执行合并，避免影响正常白班员工。
    跨夜班次（如 20:00-08:00）在月底最后一天上班时，下班卡打在下月1号。
    将下月1号的打卡存储为独立标签（如 '2026-09-01'），
    使 _bi_day_to_iso('2026-09-01', '2026-08') → '2026-09-01'，
    审核时 bi_index 能按 (name, '2026-09-01') 检索到跨夜下班卡。
    """
    if not next_records or not cross_night_employees:
        return current_records

    next_month = _next_month(audit_month)
    if not next_month:
        return current_records
    # 标准化为 YYYY-MM-DD 格式，使 _bi_day_to_iso 能正确识别
    m_nm = re.match(r"(\d{4})[-年.]?(\d{1,2})", next_month)
    next_month_norm = f"{int(m_nm.group(1)):04d}-{int(m_nm.group(2)):02d}" if m_nm else next_month
    next_day1_label = f"{next_month_norm}-01"

    next_day1_map: dict[str, list[str]] = {}
    for rec in next_records:
        name = normalize_employee_name(rec.get("employee_name", ""))
        if not name or name not in cross_night_employees:
            continue
        att = rec.get("attendance", {}) or {}
        for label, clocks in att.items():
            digits = re.sub(r"\D", "", str(label or ""))
            if not digits:
                continue
            day = int(digits[-2:]) if len(digits) >= 2 else int(digits)
            if day == 1:
                if isinstance(clocks, list):
                    next_day1_map[name] = list(clocks)
                else:
                    next_day1_map[name] = [str(clocks)]
                break

    if not next_day1_map:
        return current_records

    merged = []
    merged_names = set()
    for rec in current_records:
        name = normalize_employee_name(rec.get("employee_name", ""))
        att = dict(rec.get("attendance", {}) or {})
        if name in next_day1_map:
            att[next_day1_label] = next_day1_map[name]
        merged.append({**rec, "attendance": att})
        merged_names.add(name)

    for name, clocks in next_day1_map.items():
        if name not in merged_names:
            template = next((r for r in next_records if normalize_employee_name(r.get("employee_name", "")) == name), None)
            if template:
                merged.append({
                    **template,
                    "attendance": {next_day1_label: clocks},
                })

    return merged


def _bi_day_to_iso_local(label, audit_month: str) -> str:
    """把 BI 的 '1日' / '1' / '2026-09-01' 转成 ISO 日期（用于跨项目兜底检索）。"""
    text = str(label or "").strip()
    m_iso = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if m_iso:
        return f"{int(m_iso.group(1)):04d}-{int(m_iso.group(2)):02d}-{int(m_iso.group(3)):02d}"
    digits = re.sub(r"\D", "", text)
    if not digits:
        return ""
    day = int(digits[-2:]) if len(digits) >= 2 else int(digits)
    m = re.match(r"(\d{4})[-年.]?(\d{1,2})", str(audit_month or ""))
    if not m:
        return ""
    prefix = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    return f"{prefix}-{day:02d}"


def _collect_schedule_name_days(position_infos) -> dict:
    """从岗位排班中收集 (归一化姓名 -> 排班日期集合)，用于跨项目代班兜底检索。"""
    name_days: dict = {}
    for pi in position_infos:
        for p in pi.positions:
            for slot in p.slots:
                for work_date, cells in slot.daily.items():
                    for cell in cells:
                        for name in cell.get("names", []):
                            nn = normalize_employee_name(name)
                            if nn:
                                name_days.setdefault(nn, set()).add(work_date)
    return name_days


def _enrich_bi_cross_project(position_infos, bi_records, audit_month):
    """跨项目代班兜底检索（优化 BI 查询逻辑）。

    规则：
      1) 排班中出现的人员，若已在本项目 BI 子集里 → 维持原逻辑（直接用本项目数据）。
      2) 若本项目 BI 查无此人 → 以『姓名』为条件到当月全量 BI 中检索：
         - 仅匹配 1 人 → 直接采用该人员 BI 数据（并入 bi_records 并标记来源项目）。
         - 匹配多人   → 不直接采用，生成人工复核条目（列出每人姓名/原属项目/当日打卡时间），
                        交由审核员确认代班归属；该人员当天考勤仍按"未匹配"处理。
    返回 (enriched_bi_records, resolved_list, review_list)。
    """
    # 本项目已有姓名集合（原逻辑：本项目子集优先）
    current_names = {
        normalize_employee_name(r.get("employee_name", ""))
        for r in bi_records
    }
    current_names.discard("")

    schedule_name_days = _collect_schedule_name_days(position_infos)

    # 当月全量 BI（仅一次查询），按归一化姓名建索引
    all_month = bi_dao.get_bi_by_month(audit_month)
    month_index: dict = {}
    for r in all_month:
        nn = normalize_employee_name(r.get("employee_name", ""))
        if nn:
            month_index.setdefault(nn, []).append(r)

    enriched = list(bi_records)
    resolved_list: list = []   # 已自动归并的跨项目代班（可追溯）
    review_list: list = []      # 需人工复核的代班人员

    for sname, sch_days in schedule_name_days.items():
        if sname in current_names:
            continue  # 原逻辑：本项目已有该人，不跨项目检索
        cands = month_index.get(sname, [])
        if not cands:
            continue  # 全量 BI 也无此人 → 维持原判定（大概率真缺勤）
        if len(cands) == 1:
            # 情形一：当月全量 BI 中仅此一人同名 → 直接采用
            rec = dict(cands[0])
            rec["resolved_cross_project"] = True
            rec["source_project_name"] = rec.get("project_name", "")
            enriched.append(rec)
            resolved_list.append({
                "schedule_name": sname,
                "employee_id": rec.get("employee_id", ""),
                "source_project_name": rec.get("project_name", ""),
                "scheduled_dates": sorted(sch_days),
            })
        else:
            # 情形二：当月全量 BI 中多人同名 → 列出候选，交人工复核
            candidates = []
            for c in cands:
                att = c.get("attendance", {}) or {}
                by_date: dict = {}
                for label, clocks in att.items():
                    iso = _bi_day_to_iso_local(label, audit_month)
                    if iso and iso in sch_days:
                        cl = [str(x).strip() for x in (clocks or []) if x and str(x).strip()]
                        if cl:
                            by_date[iso] = cl
                candidates.append({
                    "employee_name": c.get("employee_name", ""),
                    "employee_id": c.get("employee_id", ""),
                    "project_name": c.get("project_name", ""),
                    "clock_by_date": by_date,
                })
            review_list.append({
                "schedule_name": sname,
                "scheduled_dates": sorted(sch_days),
                "candidates": candidates,
                "message": (
                    f"代班人员『{sname}』在当月全量 BI 中匹配到 {len(cands)} 名同名人员"
                    f"（可能跨项目），需人工确认归属"
                ),
            })

    return enriched, resolved_list, review_list


def _prune_for_confirmation(data: dict) -> dict:
    """确认页裁剪：results_json 只保留 s04_attendance_audit（扣款明细+汇总）。

    完整结果树含全月×全岗位的 slot_details，大项目 1~1.5MB；确认页只用
    s04 部分。versions_json/logs_json/summary_json 确认页均不消费，一并摘掉。
    其它调用方（审核结果页等）不传 scope，行为不变。
    """
    payload = data.get("results_json")
    parsed = payload
    for _ in range(2):  # 兼容双重编码（JSON 列里存的是 JSON 字符串）
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except (json.JSONDecodeError, TypeError):
                parsed = None
                break
        break
    s04 = parsed.get("s04_attendance_audit") if isinstance(parsed, dict) else None
    data["results_json"] = {"s04_attendance_audit": s04 or {}}
    data["summary_json"] = None
    data["versions_json"] = None
    data["logs_json"] = None
    return data


def get_audit_result(
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str,
    scope: str = "",
) -> dict:
    """获取审核结果（按四列定位键，服务类型必填）。

    scope="confirmation" 时返回裁剪版（仅确认页所需字段，大幅减小传输体积）。
    """
    service_type = require_service_type(service_type)
    result = audit_result_dao.get_audit_result(project_name, business_type, audit_month, service_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"未找到「{service_type}」的审核结果")
    data = result.to_dict()
    if scope == "confirmation":
        return _prune_for_confirmation(data)
    return data


def list_audit_results(
    project_name: str = "",
    audit_month: str = "",
    business_type: str = "",
) -> list[dict]:
    """列出审核结果：列表查询不走定位键，保持列出全部服务类型（供前端做子分类导航）。

    列表场景只消费元数据（项目/业态/月份/服务类型/状态/版本），
    剔除 results_json 等大字段——全表 126 行全量返回约 35MB，
    曾导致服务类型按钮与结果页兜底加载明显变慢。
    """
    results = audit_result_dao.list_audit_results(project_name, audit_month, business_type)
    slim: list[dict] = []
    for r in results:
        d = r.to_dict()
        d.pop("results_json", None)
        d.pop("summary_json", None)
        d.pop("versions_json", None)
        d.pop("logs_json", None)
        slim.append(d)
    return slim


def start_audit(
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str = "",
) -> dict:
    """开始审核：加载岗位(含排班槽位) + 同项目 BI 考勤，跑槽位级三源审核并落库。

    服务类型是 (项目, 业态, 月份, 服务类型) 定位键的第四列，**必填**：
    缺失时直接报「缺少「服务类型」字段数据」，不做分支判断、不回退到空值或另一类服务。

    返回统一 Result 结构：{ code, message, data }。
    """
    service_type = require_service_type(service_type)

    logger.info(f"{'='*60}")
    logger.info(f"[审核开始] project_name={project_name}, business_type={business_type}, service_type={service_type}, audit_month={audit_month}")
    logger.info(f"{'='*60}")

    result = audit_result_dao.get_audit_result(project_name, business_type, audit_month, service_type)

    # 1) 加载岗位信息（含排班槽位）
    logger.info(f"[步骤1] 加载岗位信息...")
    # service_type 必须参与岗位定位：同一 (项目, 业态, 月份) 下保安与保洁各存一份排班，
    # 否则选「保安」审核会加载保洁的排班，审核结果内容全是保洁岗人员。
    position_info = position_dao.get_position_info(
        project_name, business_type, audit_month, service_type
    )
    if position_info is None or not position_info.positions:
        # 区分失败原因，精准提示用户下一步操作（绝不回退取用另一类服务的数据）
        if position_info is not None:
            # 记录存在但岗位列表为空 → Excel 解析出的岗位数为 0
            logger.warning(f"  - [岗位缺失] 业态 {business_type!r}/{service_type!r} 有记录但岗位列表为空（解析结果为空）")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"业态「{business_type}」服务类型「{service_type}」的岗位数据存在，但岗位列表为空，"
                    "通常是 Excel 的「合同编制表」未被正确解析。"
                    "请重新上传岗位/排班 Excel，并核对岗位名称列、业态列是否填写规范。"
                ),
            )
        # position_info 为 None → 该定位键下无匹配行，先查该范围下已有哪些服务类型
        available_sts = position_dao.list_service_types_for_scope(
            project_name, business_type, audit_month
        )
        if available_sts:
            logger.info(
                f"  - [服务类型不匹配] service_type={service_type!r} 无数据；"
                f"该项目 {audit_month} {business_type!r} 下已有的服务类型为: {available_sts}"
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Excel 表内业态不匹配：业态「{business_type}」下"
                    f"已上传的服务类型为：{'、'.join(available_sts)}，"
                    f"未找到「{service_type}」的岗位数据。\n"
                    f"请检查上传的 Excel 中「项目基础信息」Sheet 是否包含"
                    f"「{business_type}」业态，以及「合同编制表」中的业态名称是否与基础信息表一致。"
                ),
            )
        # 该范围下完全没数据 → 继续查其他业态
        uploaded_types = position_dao.list_uploaded_business_types(project_name, audit_month)
        if uploaded_types:
            logger.info(
                f"  - [岗位缺失] business_type={business_type!r} 无匹配；"
                f"该项目 {audit_month} 已上传的业态为: {uploaded_types}"
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"业务类型不匹配：未找到业态「{business_type}」的岗位数据。"
                    f"该项目 {audit_month} 已上传岗位数据的业态为：{'、'.join(uploaded_types)}，"
                    "请在项目选择处切换到对应业态后再审核（无需重新上传 Excel）。"
                ),
            )
        logger.warning(f"  - [岗位缺失] 该项目 {audit_month} 尚未上传任何岗位数据")
        raise HTTPException(
            status_code=400,
            detail="未找到该项目的岗位数据，请先上传岗位/排班 Excel",
        )
    logger.info(f"  - 岗位数量: {len(position_info.positions)}")
    for p in position_info.positions:
        logger.info(f"  - 岗位: {p.position_name}, 排班槽位数: {len(p.slots)}, 小时费率: {p.hourly_rate}")

    # 2) 加载同项目同月份 BI 考勤
    logger.info(f"[步骤2] 加载 BI 考勤数据 (audit_month={audit_month}, project_name={project_name})...")
    bi_records = bi_dao.get_bi_by_project(audit_month, project_name)
    if not bi_records:
        raise HTTPException(
            status_code=400,
            detail="未找到该项目的 BI 考勤数据，请先导入 BI 考勤",
        )
    logger.info(f"  - BI 记录数: {len(bi_records)}")
    for rec in bi_records[:5]:
        logger.info(f"  - 员工: {rec.get('employee_name')}, 工号: {rec.get('employee_id')}, 打卡天数: {len(rec.get('attendance', {}))}")
    if len(bi_records) > 5:
        logger.info(f"  - ... 还有 {len(bi_records) - 5} 条记录")

    # 2.5) 加载下月1号 BI 数据，合并到当月记录中
    # 跨夜班次（如 22:00-06:00）月底最后一天的下班卡打在下月1号，
    # 合并后审核时才能看到完整的跨夜打卡记录
    # 只对当月最后一天有跨夜班次的员工执行合并，避免影响正常白班员工
    cross_night_employees = _find_cross_night_employees_on_last_day([position_info], audit_month)
    if cross_night_employees:
        logger.info(f"  - 当月最后一天有跨夜班次的员工: {cross_night_employees}")
        next_month = _next_month(audit_month)
        if next_month:
            next_bi_records = bi_dao.get_bi_by_project(next_month, project_name)
            if next_bi_records:
                logger.info(f"  - 加载下月({next_month}) BI 数据: {len(next_bi_records)} 条，合并1号打卡...")
                bi_records = _merge_next_month_bi(bi_records, next_bi_records, audit_month, cross_night_employees)
            else:
                logger.warning(f"  - 下月({next_month}) 无 BI 数据，跳过合并")

    # 2.6) 跨项目代班兜底：排班中出现的人员若不在本项目 BI 子集，按姓名到当月全量 BI 检索
    #      - 仅匹配 1 人 → 直接并入 bi_records（标记来源项目）
    #      - 匹配多人   → 生成人工复核条目，不自动采用
    bi_records, cross_sub_resolved, cross_sub_review = _enrich_bi_cross_project(
        [position_info], bi_records, audit_month
    )
    if cross_sub_resolved:
        logger.info(f"  - 跨项目代班自动归并 {len(cross_sub_resolved)} 人: "
              + ", ".join(r["schedule_name"] + f"(←{r['source_project_name']})" for r in cross_sub_resolved))
    if cross_sub_review:
        logger.info(f"  - 跨项目代班需人工复核 {len(cross_sub_review)} 人: "
              + ", ".join(r["schedule_name"] for r in cross_sub_review))

    # 3) 跑槽位级三源审核（排班表 × BI 打卡）
    # 岗位缺编扣款 = 缺岗天数 × 日服务费 × 合同缺编系数，
    # 故先在激活合同里取系数再传入槽位审核
    logger.info(f"[步骤3] 执行槽位级三源审核...")
    absence_coefficient = get_absence_coefficient(_load_active_s04_rules(project_name, business_type, service_type))
    audit_out = run_slot_audit([position_info], bi_records, audit_month, absence_coefficient)
    # 跨项目代班兜底结果随审核输出落库，供前端展示与人工复核
    audit_out["cross_project_substitute_resolved"] = cross_sub_resolved
    audit_out["cross_project_substitute_review"] = cross_sub_review
    slot_details = audit_out.get("slot_details", [])
    summary = audit_out.get("summary", [])
    logger.info(f"  - 槽位审核记录数: {len(slot_details)}")
    logger.info(f"  - 岗位汇总数: {len(summary)}")
    for s in summary:
        logger.info(f"  - 岗位: {s.get('position')}, 槽位: {s.get('slot_index')}, 应出勤: {s.get('required_days')}, 正常: {s.get('normal_days')}, 缺岗: {s.get('shortage_days')}, 减岗: {s.get('reduction_days')}, 待复核: {s.get('pending_days')}")

    # 4) 加载合同 S04 考勤管理规则
    logger.info(f"[步骤4] 加载合同 S04 规则...")
    contracts = contract_dao.get_contracts(project_name, business_type)
    logger.info(f"  - 找到合同数: {len(contracts)}")
    s04_rules = _load_active_s04_rules(project_name, business_type, service_type)
    if s04_rules:
        logger.info(f"  - S04 规则: {s04_rules}")

    missing_fields = []
    if not s04_rules:
        missing_fields.append("S04 考勤规则")
    else:
        if not s04_rules.get("late_early_tiers"):
            missing_fields.append("迟到/早退扣款细则")
        if not s04_rules.get("missing_clock_deduction"):
            missing_fields.append("漏打卡扣款")
        if not s04_rules.get("contract_deduction_coefficient"):
            missing_fields.append("缺编系数")
    if missing_fields:
        detail = "、".join(missing_fields)
        raise HTTPException(
            status_code=400,
            detail=f"合同规则不完整，缺少：{detail}。请先在合同管理中编辑补全后再审核。",
        )

    # 5) 跑 S04 考勤管理扣款审核（人员级：迟到/早退/漏打卡/缺岗）
    if s04_rules:
        logger.info(f"[步骤5] 执行 S04 考勤扣款审核...")
        s04_audit = run_attendance_s04_audit(
            [position_info], bi_records, s04_rules, audit_month
        )
        audit_out["s04_attendance_audit"] = s04_audit
        s04_summary = s04_audit.get("summary", {})
        absence_multiplier = (
            (s04_audit.get("s04_rules", {}) or {}).get("absence_penalty_multiplier")
            or get_absence_coefficient(s04_rules)
        )
        logger.info(f"  - 缺岗扣款倍数: 当日服务费 × {absence_multiplier}")
        logger.info(f"  - 漏打卡扣款: {s04_summary.get('total_missing_clock_amount', 0)}")
        logger.info(f"  - 迟到扣款: {s04_summary.get('total_late_amount', 0)}")
        logger.info(f"  - 早退扣款: {s04_summary.get('total_early_leave_amount', 0)}")
        logger.info(f"  - 缺岗扣款: {s04_summary.get('total_absence_amount', 0)}")
        logger.info(f"  - 总扣款: {s04_summary.get('total_deduction', 0)}")
    else:
        audit_out["s04_attendance_audit"] = {"message": "无 S04 规则，跳过"}

    # 6) 落库（UPSERT）
    logger.info(f"[步骤6] 落库...")
    # 项目名称一律取其原始值（与上传编制表时写入 position_infos 的项目名完全一致），
    # 不再做「去掉"项目"二字」的替换 —— 旧逻辑会把落库名（如"长春金鹰世界"）与
    # 查询/比对用的原值（如"长春金鹰世界项目"）折成两把键：既让版本号永不递增，
    # 又使审核结果行与编制表行对不上。现在两侧统一用登录用户绑定的原始项目名。
    new_version = (result.version + 1) if result else 1
    out = AuditResult(
        project_name=project_name,
        business_type=business_type,
        service_type=service_type,
        audit_month=audit_month,
        status=AuditStatus.AUDITED,
        version=new_version,
        results_json=json_dumps(audit_out),
        summary_json=json_dumps(audit_out["summary"]),
        ai_analysis="",
        versions_json="[]",
        logs_json="[]",
        confirmed_by="",
        confirmed_at="",
    )
    audit_result_dao.save_audit_result(out)
    logger.info(f"  - 版本: {new_version}, 已保存")

    # 同步驾驶舱摘要表（派生数据，失败不阻断审核主流程）
    from app.api.v2.service.dashboard_service import upsert_audit_summary
    upsert_audit_summary(
        project_name, business_type, audit_month, service_type,
        status=AuditStatus.AUDITED, confirmed_at="", data=audit_out,
    )

    logger.info(f"{'='*60}")
    logger.info(f"[审核完成] 总槽位数: {len(slot_details)}, 总扣款: {s04_summary.get('total_deduction', 0) if s04_rules else 0}")
    logger.info(f"{'='*60}\n")

    # 统一口径：
    # 分子 = 异常记录数（个人考勤异常总条数：漏打卡+中间卡+迟到+早退+缺勤）
    # 分母 = 排班任务数（slot_details 中排除休息/请假的条数）
    s04_audit_data = audit_out.get("s04_attendance_audit") or {}
    deduction_details_list = s04_audit_data.get("deduction_details", []) if isinstance(s04_audit_data, dict) else []
    exception_count = sum(
        len(d.get("missing_clock_dates", [])) +
        len(d.get("mid_clock_issues", [])) +
        len(d.get("late_details", [])) +
        len(d.get("early_leave_details", [])) +
        len(d.get("absence_dates", []))
        for d in deduction_details_list
    )
    schedule_task_count = sum(1 for d in slot_details if d.get("status") not in ("休息", "请假"))

    return Result.ok(
        {
            "project_name": project_name,
            "business_type": business_type,
            "audit_month": audit_month,
            "version": new_version,
            "status": AuditStatus.AUDITED,
            "slot_count": schedule_task_count,
            "exception_count": exception_count,
            "summary": audit_out["summary"],
        },
        message="审核完成",
    ).to_dict()




def update_audit_result(
    project_name: str,
    business_type: str,
    audit_month: str,
    results_json: list | None = None,
    summary_json: list | None = None,
    status: str | None = None,
    service_type: str = "",
) -> dict:
    """审核员手动修改审核结果（只改指定服务类型的那一条）。"""
    service_type = require_service_type(service_type)
    result = audit_result_dao.get_audit_result(project_name, business_type, audit_month, service_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"未找到「{service_type}」的审核结果")

    from app.api.v2.core.database import json_dumps

    audit_result_dao.update_audit_result_fields(
        project_name, business_type, audit_month,
        service_type=service_type,
        results_json=json_dumps(results_json) if results_json is not None else None,
        summary_json=json_dumps(summary_json) if summary_json is not None else None,
        status=status,
    )
    updated = audit_result_dao.get_audit_result(project_name, business_type, audit_month, service_type)
    return updated.to_dict()


def validate_free_deduction_limits(
    deduction_details: list[dict],
    confirmed_records: list[dict],
) -> None:
    """免打卡次数上限校验（防绕过）。

    提交即代表该员工「期望的最终免打卡集合」。按员工汇总本次提交的
    免打卡条数，不得超过其月度免打卡额度；超出则拒绝并提示「剩余次数不足」。

    说明：前端每次提交都携带该员工全部异常记录（已免/未免）的完整状态，
    因此「本批次提交的免打卡条数」即为提交后的最终免打卡条数，与现有
    已确认记录口径一致；即便请求绕过前端、只携带新增的免打卡条目，
    本校验同样会拦截超额提交，杜绝绕过。
    """
    free_limit_by_emp: dict[str, int] = {}
    for d in deduction_details:
        emp = d.get("employee_name", "")
        if emp:
            free_limit_by_emp[emp] = int(d.get("missing_clock_free_limit") or 0)

    batch_free_by_emp: dict[str, int] = {}
    for r in confirmed_records:
        if r.get("free_deduction"):
            emp = r.get("employee_name", "")
            batch_free_by_emp[emp] = batch_free_by_emp.get(emp, 0) + 1

    for emp, cnt in batch_free_by_emp.items():
        limit = free_limit_by_emp.get(emp)
        if limit is None:
            limit = 3  # 与前端兜底默认值一致
        if cnt > limit:
            raise HTTPException(
                status_code=400,
                detail=f"{emp} 剩余次数不足，免打卡次数不可超过 {limit} 次",
            )


def confirm_exceptions(
    project_name: str,
    business_type: str,
    audit_month: str,
    confirmed_records: list[dict],
    confirmed_by: str,
    service_type: str = "",
) -> dict:
    """异常确认：**直接修改**这一份审核结果，而不是生成新结果。

    执行三件事（顺序固定）：
      1. 把确认/免扣标记写入该结果的 deduction_details[].confirmations；
      2. 按唯一「计入」规则就地重算并覆盖金额与计数（recompute_audit_totals）；
      3. 把该结果标记为「已确认」——此后它就是唯一最终版。

    confirmed_records: [
        {"employee_name": "张三", "work_date": "2026-07-01", "exception_type": "missing_clock", "confirmed": True, "confirm_note": ""},
        {"employee_name": "张三", "work_date": "2026-07-02", "exception_type": "late", "confirmed": True, "confirm_note": ""},
        ...
    ]
    """
    from app.api.v2.core.database import json_dumps, json_loads, now_text

    service_type = require_service_type(service_type)
    result = audit_result_dao.get_audit_result(project_name, business_type, audit_month, service_type)
    if not result:
        raise HTTPException(status_code=404, detail=f"未找到「{service_type}」的审核结果")

    data = json_loads(result.results_json, {})
    s04_audit = data.get("s04_attendance_audit", {})
    deduction_details = s04_audit.get("deduction_details", [])

    # 免打卡次数上限校验（防绕过）：在写入任何确认/免扣记录之前拦截超额提交。
    validate_free_deduction_limits(deduction_details, confirmed_records)

    confirm_map = {}
    for r in confirmed_records:
        key = confirm_key(
            r.get("exception_type", "missing_clock"),
            r.get("employee_name", ""),
            r.get("work_date", ""),
            r.get("window", ""),
        )
        confirm_map[key] = {
            "confirmed": r.get("confirmed", False),
            "note": r.get("confirm_note", ""),
            "free_deduction": r.get("free_deduction", False),
        }

    not_confirmed = {
        "confirmed": False,
        "note": "审核员未勾选确认",
        "free_deduction": False,
        "confirmed_by": confirmed_by,
        "confirmed_at": now_text(),
    }

    updated_count = 0
    for detail in deduction_details:
        emp_name = detail.get("employee_name", "")
        confirmations = detail.setdefault("confirmations", {})

        for date_str in detail.get("missing_clock_dates", []):
            key = confirm_key("missing_clock", emp_name, date_str)
            if key in confirm_map:
                confirmations[key] = {
                    "confirmed": confirm_map[key]["confirmed"],
                    "note": confirm_map[key]["note"],
                    "free_deduction": confirm_map[key].get("free_deduction", False),
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now_text(),
                }
                updated_count += 1
            else:
                confirmations[key] = not_confirmed

        # 中间卡缺失：并入「漏打卡」确认键（与审核汇总/报告口径一致），
        # 同时保留 mid_clock| 键以兼容历史已确认数据。
        for issue in detail.get("mid_clock_issues", []):
            date_str = issue.get("date", "")
            window = issue.get("window", "")
            mc_key = confirm_key("missing_clock", emp_name, date_str, window)
            legacy_key = confirm_key("mid_clock", emp_name, date_str, window)
            src = confirm_map.get(mc_key) or confirm_map.get(legacy_key)
            if src is not None:
                conf_entry = {
                    "confirmed": src["confirmed"],
                    "note": src["note"],
                    "free_deduction": src.get("free_deduction", False),
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now_text(),
                }
                confirmations[mc_key] = conf_entry
                confirmations[legacy_key] = conf_entry
                updated_count += 1
            else:
                confirmations[mc_key] = not_confirmed
                confirmations[legacy_key] = not_confirmed

        for late in detail.get("late_details", []):
            key = confirm_key("late", emp_name, late.get("date", ""))
            if key in confirm_map:
                confirmations[key] = {
                    "confirmed": confirm_map[key]["confirmed"],
                    "note": confirm_map[key]["note"],
                    "free_deduction": confirm_map[key].get("free_deduction", False),
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now_text(),
                }
                updated_count += 1
            else:
                confirmations[key] = not_confirmed

        for early in detail.get("early_leave_details", []):
            key = confirm_key("early_leave", emp_name, early.get("date", ""))
            if key in confirm_map:
                confirmations[key] = {
                    "confirmed": confirm_map[key]["confirmed"],
                    "note": confirm_map[key]["note"],
                    "free_deduction": confirm_map[key].get("free_deduction", False),
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now_text(),
                }
                updated_count += 1
            else:
                confirmations[key] = not_confirmed

        for date_str in detail.get("absence_dates", []):
            key = confirm_key("absence", emp_name, date_str)
            if key in confirm_map:
                confirmations[key] = {
                    "confirmed": confirm_map[key]["confirmed"],
                    "note": confirm_map[key]["note"],
                    "free_deduction": confirm_map[key].get("free_deduction", False),
                    "confirmed_by": confirmed_by,
                    "confirmed_at": now_text(),
                }
                updated_count += 1
            else:
                confirmations[key] = not_confirmed

    data["s04_attendance_audit"] = s04_audit

    # 就地定稿：按唯一「计入」规则重算金额，并把这份结果标记为唯一最终版。
    recompute_audit_totals(data)
    audit_result_dao.update_audit_result_fields(
        project_name, business_type, audit_month,
        service_type=service_type,
        results_json=json_dumps(data),
        confirmed_by=confirmed_by,
        confirmed_at=now_text(),
        status=AuditStatus.CONFIRMED,
    )

    # 同步驾驶舱摘要表（定稿口径，失败不阻断主流程）
    from app.api.v2.service.dashboard_service import upsert_audit_summary
    upsert_audit_summary(
        project_name, business_type, audit_month, service_type,
        status=AuditStatus.CONFIRMED, confirmed_at=now_text(), data=data,
    )

    return {
        "updated_count": updated_count,
        "message": f"已确认{updated_count}条记录",
        **audit_totals_metrics(data),
    }
