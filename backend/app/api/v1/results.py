from urllib.parse import unquote

from fastapi import APIRouter, HTTPException, Query, Header
from pydantic import BaseModel
from app.core.database import get_conn, json_loads, json_dumps, now_text

router = APIRouter()

def normalize_role(value: str) -> str:
    value = unquote(str(value or ""))
    return "项目账号" if value in {"项目账号", "project_user"} else "集团管理员"

def decode_header_value(value: str) -> str:
    return unquote(str(value or ""))

def _results(batch_id: int, x_user_role: str = "集团管理员", x_project_name: str = ""):
    with get_conn() as conn:
        row = conn.execute("SELECT project_name,results_json FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        if normalize_role(x_user_role) == "项目账号" and x_project_name and row["project_name"] != decode_header_value(x_project_name):
            raise HTTPException(status_code=403, detail="项目账号不能查看其他项目数据")
        return json_loads(row["results_json"], {})

@router.get("/results/attendance-details")
def attendance_details(batch_id: int = Query(...), x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    return _results(batch_id, x_user_role, x_project_name).get("attendance_details", [])

@router.get("/results/position-fulfillment")
def position_fulfillment(batch_id: int = Query(...), x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    return _results(batch_id, x_user_role, x_project_name).get("position_fulfillment", [])

@router.get("/results/exceptions")
def exceptions(batch_id: int = Query(...), x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    return _results(batch_id, x_user_role, x_project_name).get("exception_statistics", [])

@router.get("/results/attendance-deductions")
def attendance_deductions(batch_id: int = Query(...), x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    return _results(batch_id, x_user_role, x_project_name).get("attendance_deductions", [])

@router.get("/results/deductions")
def deductions(batch_id: int = Query(...), x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    return _results(batch_id, x_user_role, x_project_name).get("deduction_summary", [])


class AttendanceProofUpdate(BaseModel):
    """更新单条漏打卡记录的出勤证明状态"""
    employee_name: str
    work_date: str
    has_proof: bool


@router.put("/results/{batch_id}/attendance-proof")
def update_attendance_proof(
    batch_id: int,
    payload: AttendanceProofUpdate,
    x_user_role: str = Header("集团管理员"),
    x_project_name: str = Header(""),
):
    """更新单条漏打卡记录的出勤证明状态。
    has_proof=True 时扣款金额改为0，has_proof=False 时恢复扣款。
    """
    data = _results(batch_id, x_user_role, x_project_name)
    details = data.get("attendance_details", [])
    updated = False
    for d in details:
        if d.get("employee_name") == payload.employee_name and d.get("work_date") == payload.work_date:
            # 找到该条记录，更新漏打卡的出勤证明状态和扣款金额
            d["has_attendance_proof"] = payload.has_proof
            items = d.get("deduction_items", [])
            new_items = []
            old_amount = 0
            for item in items:
                if isinstance(item, list) and len(item) >= 3 and item[0] == "漏打卡":
                    old_amount = item[1]
                    if payload.has_proof:
                        new_items.append(["漏打卡", 0, f"疑似漏打卡，已提供出勤证明，免扣款"])
                    else:
                        # 恢复扣款金额
                        amount = old_amount if old_amount > 0 else 50
                        new_items.append(["漏打卡", amount, f"疑似漏打卡，未提供出勤证明，扣款{amount}元"])
                else:
                    new_items.append(item)
            d["deduction_items"] = new_items
            # 重新计算总扣款
            total = sum(item[1] for item in new_items if isinstance(item, list) and len(item) >= 2)
            d["deduction_amount"] = round(total, 2)
            updated = True
            break
    if not updated:
        raise HTTPException(status_code=404, detail="未找到对应的漏打卡记录")
    # 更新汇总数据
    deductions = data.get("attendance_deductions", [])
    for dd in deductions:
        if dd.get("employee_name") == payload.employee_name:
            # 重新计算该员工总扣款
            emp_total = sum(
                d["deduction_amount"]
                for d in details
                if d.get("employee_name") == payload.employee_name
            )
            dd["total_deduction"] = round(emp_total, 2)
            break
    # 写回数据库
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_batches SET results_json=? WHERE id=?",
            (json_dumps(data), batch_id),
        )
    return {"ok": True, "message": "出勤证明状态已更新"}


class ConfirmRecord(BaseModel):
    """单条异常记录确认"""
    employee_name: str
    work_date: str
    confirmed: bool
    confirm_note: str = ""


class BatchConfirm(BaseModel):
    """批量确认异常记录"""
    confirmed_records: list[ConfirmRecord]
    confirmed_by: str = ""


@router.put("/results/{batch_id}/confirm-exceptions")
def confirm_exceptions(batch_id: int, payload: BatchConfirm, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    """项目确认异常记录。confirmed=True表示项目确认该异常属实，confirmed=False表示项目有异议。"""
    data = _results(batch_id, x_user_role, x_project_name)
    details = data.get("attendance_details", [])
    confirm_map = {}
    for r in payload.confirmed_records:
        confirm_map[(r.employee_name, r.work_date)] = {"confirmed": r.confirmed, "note": r.confirm_note}
    updated_count = 0
    for d in details:
        key = (d.get("employee_name"), d.get("work_date"))
        if key in confirm_map:
            d["project_confirmed"] = confirm_map[key]["confirmed"]
            d["confirm_note"] = confirm_map[key]["note"]
            d["confirmed_by"] = payload.confirmed_by
            d["confirmed_at"] = now_text()
            updated_count += 1
    # 写回数据库
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_batches SET results_json=? WHERE id=?",
            (json_dumps(data), batch_id),
        )
    return {"ok": True, "updated_count": updated_count, "message": f"已确认{updated_count}条记录"}


@router.get("/results/{batch_id}/confirmation-page")
def get_confirmation_page(batch_id: int, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    """获取异常确认页面数据：只返回异常记录，供项目打勾确认"""
    data = _results(batch_id, x_user_role, x_project_name)
    details = data.get("attendance_details", [])
    # 只返回异常记录
    exceptions = [d for d in details if d.get("exception_type") and d.get("exception_type") != "正常"]
    # 按员工分组
    by_employee = {}
    for d in exceptions:
        emp = d.get("employee_name", "")
        if emp not in by_employee:
            by_employee[emp] = []
        by_employee[emp].append({
            "work_date": d.get("work_date"),
            "position": d.get("position"),
            "shift_name": d.get("shift_name"),
            "clock_times": d.get("clock_times"),
            "exception_type": d.get("exception_type"),
            "exception_reason": d.get("exception_reason"),
            "project_confirmed": d.get("project_confirmed"),
            "confirm_note": d.get("confirm_note", ""),
        })
    return {
        "batch_id": batch_id,
        "total_exceptions": len(exceptions),
        "employees": list(by_employee.keys()),
        "by_employee": by_employee,
    }


@router.post("/results/{batch_id}/finalize")
def finalize_audit(batch_id: int, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    """项目确认异常后，根据合同细则生成扣款金额并生成PDF报告。
    只对project_confirmed=True的异常记录计算扣款，未确认或未勾选的记录不扣款。
    """
    data = _results(batch_id, x_user_role, x_project_name)
    details = data.get("attendance_details", [])
    configs = data.get("rule_configs", {})
    contracts = data.get("contracts", [])
    # 加载合同规则
    active_contract = data.get("active_contract", {})
    if not active_contract:
        with get_conn() as conn:
            batch = conn.execute("SELECT project_name, business_type FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
            if batch:
                row = conn.execute(
                    "SELECT rules_json FROM project_contracts WHERE project_name=? AND status='active' ORDER BY updated_at DESC LIMIT 1",
                    (batch["project_name"],),
                ).fetchone()
                if row:
                    active_contract = json_loads(row["rules_json"], {})
    # 合并配置
    if active_contract:
        for k, v in active_contract.items():
            if k not in configs and v is not None:
                configs[k] = v

    # 重新计算扣款
    from app.services.rule_engine import calc_late_early_amount, calc_work_hours, calc_late_minutes, calc_early_minutes, normalize_position_name, load_configs

    # 加载默认配置并合并合同规则（确保所有必需字段都有值）
    default_configs = load_configs()
    for k, v in default_configs.items():
        if k not in configs or configs[k] is None:
            configs[k] = v
    # 关键默认值兜底
    configs.setdefault("late_grace_minutes", 5)
    configs.setdefault("early_grace_minutes", 5)
    configs.setdefault("late_early_over_minutes_as_absence", 60)
    configs.setdefault("minimum_work_hour_ratio", 0.9)
    configs.setdefault("attendance_deduction_coefficient", 1.2)
    configs.setdefault("missing_clock_deduction", 50)
    configs.setdefault("missing_clock_free_times_per_month", 3)
    configs.setdefault("missing_clock_free_requires_attendance_proof", True)
    configs.setdefault("late_early_tiers", [{"max_minutes": 30, "amount": 20}, {"max_minutes": 60, "amount": 50}])

    # 从合同编制表构建时薪映射
    hourly_rate_by_position = {}
    for c in contracts:
        pos = c.get("position", "")
        rate = c.get("hourly_rate", 0)
        if pos and rate:
            hourly_rate_by_position[pos] = rate

    def get_hourly_rate(position):
        if position in hourly_rate_by_position:
            return hourly_rate_by_position[position]
        norm = normalize_position_name(position)
        for key, rate in hourly_rate_by_position.items():
            k_norm = normalize_position_name(key)
            if norm and k_norm and (norm in k_norm or k_norm in norm):
                return rate
        return 0

    confirmed_count = 0
    skipped_count = 0
    for d in details:
        exception_type = d.get("exception_type", "")
        if not exception_type or exception_type == "正常":
            d["deduction_amount"] = 0
            d["deduction_items"] = []
            continue

        confirmed = d.get("project_confirmed", False)
        if not confirmed:
            # 未确认的异常不扣款
            d["deduction_amount"] = 0
            d["deduction_items"] = [["未确认", 0, "项目未确认，暂不扣款"]]
            skipped_count += 1
            continue

        confirmed_count += 1
        # 根据异常类型和合同规则计算扣款
        deduction_items = []
        position = d.get("position", "")
        standard_hours = float(d.get("shift_hours", 8) or 8)
        hourly_rate = get_hourly_rate(position)
        deduction_coeff = float(configs.get("attendance_deduction_coefficient", 1.2) or 1.2)
        clock_times_str = d.get("clock_times", "")
        clock_times = [t.strip() for t in clock_times_str.split("、") if t.strip()] if clock_times_str else []

        if "缺勤" in exception_type:
            amount = round(standard_hours * hourly_rate * deduction_coeff, 2)
            deduction_items.append(["缺勤", amount, f"{standard_hours} × {hourly_rate} × {deduction_coeff}"])
        elif "疑似漏打卡" in exception_type:
            clock_deduction = round(float(configs.get("missing_clock_deduction", 50) or 50), 2)
            has_proof = d.get("has_attendance_proof", False)
            if has_proof:
                deduction_items.append(["漏打卡", 0, "已提供出勤证明，免扣款"])
            else:
                deduction_items.append(["漏打卡", clock_deduction, f"疑似漏打卡，扣款{clock_deduction}元"])
        elif "迟到" in exception_type or "早退" in exception_type:
            # 需要班次信息来计算迟到/早退分钟
            shift = {"start_time": d.get("shift_start_time", "08:00"), "end_time": d.get("shift_end_time", "17:00")}
            over_threshold = float(configs.get("late_early_over_minutes_as_absence", 60) or 60)
            late_min = calc_late_minutes(clock_times, shift, configs) if clock_times else 0
            early_min = calc_early_minutes(clock_times, shift, configs) if clock_times else 0
            converted = False
            if late_min > 0:
                amount, calc = calc_late_early_amount(late_min, standard_hours, hourly_rate, configs)
                if late_min > over_threshold:
                    # 转为缺勤
                    absence_amount = round(standard_hours * hourly_rate * deduction_coeff, 2)
                    deduction_items.append(["迟到转缺勤", absence_amount, f"迟到{late_min}分钟超{over_threshold}分钟，按缺勤处理"])
                    converted = True
                else:
                    deduction_items.append(["迟到", amount, calc])
            if early_min > 0:
                amount, calc = calc_late_early_amount(early_min, standard_hours, hourly_rate, configs)
                if early_min > over_threshold:
                    absence_amount = round(standard_hours * hourly_rate * deduction_coeff, 2)
                    deduction_items.append(["早退转缺勤", absence_amount, f"早退{early_min}分钟超{over_threshold}分钟，按缺勤处理"])
                    converted = True
                else:
                    deduction_items.append(["早退", amount, calc])
            # 工时不足
            if not converted:
                actual_hours = calc_work_hours(clock_times) if clock_times else 0
                min_ratio = float(configs.get("minimum_work_hour_ratio", 0.8) or 0.8)
                if actual_hours < standard_hours * min_ratio:
                    shortage = max(standard_hours - actual_hours, 0)
                    amount = round(shortage * hourly_rate * deduction_coeff, 2)
                    deduction_items.append(["工时不足", amount, f"{shortage} × {hourly_rate} × {deduction_coeff}"])
        elif "工时不足" in exception_type:
            actual_hours = float(d.get("actual_hours", 0) or 0)
            min_ratio = float(configs.get("minimum_work_hour_ratio", 0.8) or 0.8)
            if actual_hours < standard_hours * min_ratio:
                shortage = max(standard_hours - actual_hours, 0)
                amount = round(shortage * hourly_rate * deduction_coeff, 2)
                deduction_items.append(["工时不足", amount, f"{shortage} × {hourly_rate} × {deduction_coeff}"])
        elif "打卡时间异常" in exception_type:
            # 打卡时间异常不扣款，仅记录
            deduction_items.append(["打卡时间异常", 0, "打卡时间异常，不扣款"])

        total = sum(item[1] for item in deduction_items if len(item) >= 2)
        d["deduction_items"] = deduction_items
        d["deduction_amount"] = round(total, 2)

    # 重新计算汇总
    deductions = []
    for d in details:
        for item in d.get("deduction_items", []):
            if len(item) >= 3 and item[1] > 0:
                deductions.append({
                    "work_date": d.get("work_date"),
                    "employee_name": d.get("employee_name"),
                    "position": d.get("position"),
                    "exception_type": item[0],
                    "deduction_rule": item[0],
                    "deduction_amount": item[1],
                    "calculation_detail": item[2],
                })
    data["attendance_deductions"] = deductions

    # 重新计算扣款汇总 - 保持与原始审核相同的格式（一个总览条目）
    total_attendance_deduction = round(sum(dd["deduction_amount"] for dd in deductions), 2)
    data["deduction_summary"] = [{
        "position_deduction_amount": 0,
        "attendance_deduction_amount": total_attendance_deduction,
        "total_deduction_amount": total_attendance_deduction,
    }]

    # 同时保存按员工汇总的扣款明细（供前端展示）
    from collections import defaultdict
    emp_totals = defaultdict(float)
    for dd in deductions:
        emp_totals[dd["employee_name"]] += dd["deduction_amount"]
    emp_deduction_list = []
    for emp, total in sorted(emp_totals.items()):
        emp_records = [d for d in details if d.get("employee_name") == emp]
        emp_deduction_list.append({
            "employee_name": emp,
            "position": emp_records[0].get("position", "") if emp_records else "",
            "exception_count": len([d for d in emp_records if d.get("exception_type") and d.get("exception_type") != "正常"]),
            "total_deduction": round(total, 2),
        })
    data["employee_deduction_summary"] = emp_deduction_list

    # 更新汇总 - 使用与原始审核一致的字段名
    summary = data.get("summary", {})
    # 保存第一次审核的异常率（如果尚未保存）
    schedule_count = summary.get("schedule_task_count", 0) or 0
    first_exception_count = summary.get("exception_count", 0) or 0
    if "first_exception_rate" not in summary:
        summary["first_exception_rate"] = round(first_exception_count / schedule_count * 100, 1) if schedule_count > 0 else 0
    # 计算确认后的异常率（只计已确认的异常）
    summary["confirmed_exception_count"] = confirmed_count
    summary["confirmed_exception_rate"] = round(confirmed_count / schedule_count * 100, 1) if schedule_count > 0 else 0
    summary["total_deduction_amount"] = total_attendance_deduction
    summary["attendance_deduction_amount"] = total_attendance_deduction
    summary["position_deduction_amount"] = 0
    summary["confirmed_count"] = confirmed_count
    summary["skipped_count"] = skipped_count
    data["summary"] = summary

    # 写回数据库：同时更新 results_json 和 summary_json（Dashboard从summary_json读取扣款金额）
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_batches SET results_json=?, summary_json=? WHERE id=?",
            (json_dumps(data), json_dumps(summary), batch_id),
        )

    # 生成PDF报告：AI审核汇总与扣款报告（合并为一个PDF）
    report_error = ""
    try:
        from app.services.report_generator.pdf_report import build_combined_report_pdf
        from pathlib import Path
        from app.core.config import settings

        report_dir = Path(settings.report_dir) / str(batch_id)
        report_dir.mkdir(parents=True, exist_ok=True)

        # 先删除旧审核汇总报告（保留考勤明细），避免遗留
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM generated_reports WHERE audit_batch_id=? AND report_type LIKE '%AI审核汇总与扣款报告'",
                (batch_id,),
            )

        # 生成合并报告
        report = build_combined_report_pdf(batch_id, report_dir, data)

        with get_conn() as conn:
            conn.execute(
                "INSERT INTO generated_reports(audit_batch_id,report_type,file_format,file_path,download_url,created_at) VALUES(?,?,?,?,?,?)",
                (batch_id, report["report_type"], "pdf", report["file_path"], report["download_url"], now_text()),
            )
    except Exception as e:
        report_error = f"（报告生成失败：{e}）"

    total_deduction = summary.get("total_deduction_amount", 0)
    return {
        "ok": True,
        "confirmed_count": confirmed_count,
        "skipped_count": skipped_count,
        "total_deduction": total_deduction,
        "first_exception_rate": summary.get("first_exception_rate", 0),
        "confirmed_exception_rate": summary.get("confirmed_exception_rate", 0),
        "message": f"已根据{confirmed_count}条确认记录生成扣款，共{len(deductions)}条扣款明细，总扣款{total_deduction}元。第一次审核异常率{summary.get('first_exception_rate', 0)}%，确认后异常率{summary.get('confirmed_exception_rate', 0)}%{report_error}",
    }
