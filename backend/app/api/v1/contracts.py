from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Header
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_conn, json_dumps, json_loads, now_text

router = APIRouter()

ALLOWED_CONTRACT_EXTENSIONS = {".pdf", ".docx", ".doc"}
CONTRACT_RULE_KEYS = {
    "late_deduction_per_minute",
    "early_leave_deduction_per_minute",
    "missing_clock_deduction",
    "single_person_daily_cap",
    "late_grace_minutes",
    "early_leave_grace_minutes",
    "attendance_deduction_coefficient",
    "contract_deduction_coefficient",
    "late_early_tiers",
    "late_early_over_minutes_as_absence",
    "missing_clock_free_times_per_month",
    "missing_clock_free_requires_attendance_proof",
}

def normalize_role(value: str) -> str:
    value = unquote(str(value or ""))
    return "项目账号" if value in {"项目账号", "project_user"} else "集团管理员"

def decode_header_value(value: str) -> str:
    return unquote(str(value or ""))

class ContractStatusUpdate(BaseModel):
    is_active: bool

class ManualRulesUpdate(BaseModel):
    """手动填写扣款细则"""
    late_early_tiers: list[dict] | None = None
    late_early_over_minutes_as_absence: float | None = None
    missing_clock_deduction: float | None = None
    missing_clock_free_times_per_month: float | None = None
    missing_clock_free_requires_attendance_proof: bool | None = None
    contract_deduction_coefficient: float | None = None
    single_person_daily_cap: float | None = None

class RuleCenterUpdate(BaseModel):
    rules: dict

class RuleCenterStatusUpdate(BaseModel):
    status: str = "已确认"

def safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", Path(value).name)

def normalize_contract_project(project_name: str, project_code: str, business_type: str, original_name: str) -> tuple[str, str, str]:
    project_name = str(project_name or "").strip()
    project_code = str(project_code or "").strip()
    business_type = normalize_business_type_label(business_type)
    source = f"{project_name} {business_type} {original_name}"
    with get_conn() as conn:
        master_rows = conn.execute(
            """
            SELECT project_name,project_code,business_type
            FROM project_business_types
            WHERE status='启用'
            ORDER BY project_name,business_type
            """
        ).fetchall()
    exact_project_rows = [row for row in master_rows if row["project_name"] == project_name]
    if not exact_project_rows:
        matched_rows = [row for row in master_rows if row["project_name"] and row["project_name"] in source]
        if not matched_rows and "江宁" in source:
            matched_rows = [row for row in master_rows if row["project_name"] == "江宁金鹰天地"]
        if not matched_rows:
            raise HTTPException(status_code=400, detail="合同项目名未匹配到项目主档，请先在页面选择标准项目后再上传")
        project_name = matched_rows[0]["project_name"]
        project_code = matched_rows[0]["project_code"] or project_code
        exact_project_rows = [row for row in master_rows if row["project_name"] == project_name]
    else:
        project_code = exact_project_rows[0]["project_code"] or project_code

    allowed_business_types = {row["business_type"] for row in exact_project_rows}
    if not business_type:
        inferred = normalize_business_type_label(source)
        if inferred in allowed_business_types:
            business_type = inferred
        elif len(allowed_business_types) == 1:
            business_type = next(iter(allowed_business_types))
    if business_type not in allowed_business_types:
        raise HTTPException(status_code=400, detail=f"业态“{business_type or '未选择'}”不属于项目“{project_name}”，请重新选择项目业态")
    return project_name, project_code, business_type

def contract_to_dict(row) -> dict:
    item = dict(row)
    item["rules"] = json_loads(item.pop("rules_json", None), {})
    item["download_url"] = item["storage_path"].replace(str(settings.storage_dir), "/files").replace("\\", "/")
    return item

@router.get("/contracts")
def list_contracts(project_name: str | None = None, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    sql = "SELECT * FROM project_contracts"
    params = []
    if normalize_role(x_user_role) == "项目账号" and x_project_name:
        project_name = decode_header_value(x_project_name)
    if project_name:
        sql += " WHERE project_name=?"
        params.append(project_name)
    sql += " ORDER BY is_active DESC, updated_at DESC, id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [contract_to_dict(row) for row in rows]

@router.get("/contracts/projects")
def list_contract_projects(x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    with get_conn() as conn:
        where_sql = "WHERE p.status='启用'"
        params = []
        if normalize_role(x_user_role) == "项目账号" and x_project_name:
            where_sql += " AND p.project_name=?"
            params.append(decode_header_value(x_project_name))
        rows = conn.execute(
            f"""
            SELECT p.project_name,
                   p.project_code,
                   COUNT(DISTINCT c.id) AS contract_count,
                   COUNT(DISTINCT CASE WHEN c.is_active=1 THEN c.id END) AS active_count
            FROM project_business_types p
            LEFT JOIN project_contracts c
              ON c.project_name=p.project_name
            {where_sql}
            GROUP BY p.project_name, p.project_code
            ORDER BY p.project_name
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows if row["project_name"]]

@router.post("/contracts")
async def upload_contract(
    project_name: str = Form(""),
    project_code: str = Form(""),
    business_type: str = Form(""),
    supplier: str = Form(""),
    contract_no: str = Form(""),
    contract_name: str = Form(""),
    service_type: str = Form("保洁"),
    version: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    is_active: bool = Form(True),
    late_deduction_per_minute: str = Form(""),
    early_leave_deduction_per_minute: str = Form(""),
    missing_clock_deduction: str = Form(""),
    single_person_daily_cap: str = Form(""),
    late_grace_minutes: str = Form(""),
    early_leave_grace_minutes: str = Form(""),
    attendance_deduction_coefficient: str = Form(""),
    contract_deduction_coefficient: str = Form(""),
    file: UploadFile = File(...),
    x_user_role: str = Header("集团管理员"),
    x_project_name: str = Header(""),
):
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_CONTRACT_EXTENSIONS:
        raise HTTPException(status_code=400, detail="合同仅支持 PDF、Word（.doc/.docx）文件")
    settings.contract_dir.mkdir(parents=True, exist_ok=True)
    original_name = safe_name(file.filename)
    stored_name = f"{now_text().replace(':', '').replace(' ', '_')}_{original_name}"
    storage_path = settings.contract_dir / stored_name
    file_bytes = await file.read()
    storage_path.write_bytes(file_bytes)
    extracted = extract_contract_metadata(storage_path, original_name)
    project_name = project_name or extracted.get("project_name", "")
    project_code = project_code or extracted.get("project_code", "")
    business_type = business_type or extracted.get("business_type", "")
    supplier = supplier or extracted.get("supplier", "")
    contract_no = contract_no or extracted.get("contract_no", "")
    contract_name = contract_name or extracted.get("contract_name", "")
    service_type = service_type or extracted.get("service_type", "保洁")
    version = version or extracted.get("version", "")
    start_date = start_date or extracted.get("start_date", "")
    end_date = end_date or extracted.get("end_date", "")
    if not project_name:
        project_name = Path(file.filename).stem
    if normalize_role(x_user_role) == "项目账号" and x_project_name:
        project_name = decode_header_value(x_project_name)
    project_name, project_code, business_type = normalize_contract_project(
        project_name=project_name,
        project_code=project_code,
        business_type=business_type,
        original_name=original_name,
    )

    raw_rules = {
        "late_deduction_per_minute": late_deduction_per_minute or extracted["rules"].get("late_deduction_per_minute", ""),
        "early_leave_deduction_per_minute": early_leave_deduction_per_minute or extracted["rules"].get("early_leave_deduction_per_minute", ""),
        "missing_clock_deduction": missing_clock_deduction or extracted["rules"].get("missing_clock_deduction", ""),
        "single_person_daily_cap": single_person_daily_cap or extracted["rules"].get("single_person_daily_cap", ""),
        "late_grace_minutes": late_grace_minutes or extracted["rules"].get("late_grace_minutes", ""),
        "early_leave_grace_minutes": early_leave_grace_minutes or extracted["rules"].get("early_leave_grace_minutes", ""),
        "attendance_deduction_coefficient": attendance_deduction_coefficient or extracted["rules"].get("attendance_deduction_coefficient", ""),
        "contract_deduction_coefficient": contract_deduction_coefficient or extracted["rules"].get("contract_deduction_coefficient", ""),
    }
    rules = {}
    for key, value in raw_rules.items():
        if value is None or str(value).strip() == "" or str(value).strip() == "None":
            continue
        try:
            rules[key] = float(value)
        except (ValueError, TypeError):
            continue
    for key in [
        "late_early_tiers",
        "late_early_over_minutes_as_absence",
        "missing_clock_free_times_per_month",
        "missing_clock_free_requires_attendance_proof",
    ]:
        if key in extracted["rules"]:
            rules[key] = extracted["rules"][key]

    final_contract_name = contract_name or Path(file.filename).stem
    has_late_early_rules = "late_early_tiers" in rules or (
        "late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules
    )
    has_required_rules = has_late_early_rules and "missing_clock_deduction" in rules
    contract_status = "active" if is_active and has_required_rules else "parse_failed"
    final_is_active = 1 if is_active and has_required_rules else 0
    now = now_text()
    with get_conn() as conn:
        if final_is_active:
            conn.execute(
                "UPDATE project_contracts SET is_active=0,status='inactive',updated_at=? WHERE project_name=? AND IFNULL(business_type,'')=IFNULL(?, '') AND service_type=?",
                (now, project_name, business_type or "", service_type),
            )
        cursor = conn.execute(
            """
            INSERT INTO project_contracts(
                project_name,project_code,business_type,supplier,contract_no,contract_name,service_type,version,
                start_date,end_date,original_name,file_format,storage_path,rules_json,status,is_active,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                project_name, project_code, business_type, supplier, contract_no, final_contract_name, service_type, version,
                start_date, end_date, original_name, suffix.lstrip("."), str(storage_path), json_dumps(rules),
                contract_status, final_is_active, now, now,
            ),
        )
        row = conn.execute("SELECT * FROM project_contracts WHERE id=?", (cursor.lastrowid,)).fetchone()
        upsert_rule_center(conn, project_name, project_code, business_type, service_type, cursor.lastrowid, rules)
        return contract_to_dict(row)

@router.get("/rule-center")
def list_rule_center(project_name: str | None = None, service_type: str | None = None, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    sql = "SELECT * FROM project_rule_center"
    params = []
    conditions = []
    if normalize_role(x_user_role) == "项目账号" and x_project_name:
        project_name = decode_header_value(x_project_name)
    if project_name:
        conditions.append("project_name=?")
        params.append(project_name)
    if service_type:
        conditions.append("service_type=?")
        params.append(service_type)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY updated_at DESC,id DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [rule_center_to_dict(row) for row in rows]

@router.put("/rule-center/{rule_id}")
def update_rule_center(rule_id: int, payload: RuleCenterUpdate, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    now = now_text()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM project_rule_center WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="规则不存在")
        if normalize_role(x_user_role) == "项目账号" and x_project_name and row["project_name"] != decode_header_value(x_project_name):
            raise HTTPException(status_code=403, detail="项目账号不能修改其他项目规则")
        conn.execute(
            "UPDATE project_rule_center SET rules_json=?,status=?,updated_at=? WHERE id=?",
            (json_dumps(payload.rules), "待确认", now, rule_id),
        )
        updated = conn.execute("SELECT * FROM project_rule_center WHERE id=?", (rule_id,)).fetchone()
        return rule_center_to_dict(updated)

@router.post("/rule-center/{rule_id}/confirm")
def confirm_rule_center(rule_id: int, payload: RuleCenterStatusUpdate | None = None, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    payload = payload or RuleCenterStatusUpdate()
    if payload.status not in {"已确认", "待确认"}:
        raise HTTPException(status_code=400, detail="规则状态仅支持：待确认、已确认")
    now = now_text()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM project_rule_center WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="规则不存在")
        if normalize_role(x_user_role) == "项目账号" and x_project_name and row["project_name"] != decode_header_value(x_project_name):
            raise HTTPException(status_code=403, detail="项目账号不能确认其他项目规则")
        conn.execute(
            "UPDATE project_rule_center SET status=?,confirmed_at=?,updated_at=? WHERE id=?",
            (payload.status, now if payload.status == "已确认" else None, now, rule_id),
        )
        updated = conn.execute("SELECT * FROM project_rule_center WHERE id=?", (rule_id,)).fetchone()
        return rule_center_to_dict(updated)

@router.put("/contracts/{contract_id}/active")
def update_contract_active(contract_id: int, payload: ContractStatusUpdate):
    now = now_text()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM project_contracts WHERE id=?", (contract_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="合同不存在")
        rules = json_loads(row["rules_json"], {})
        has_late_early = "late_early_tiers" in rules or ("late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules)
        if payload.is_active and (not has_late_early or "missing_clock_deduction" not in rules):
            raise HTTPException(status_code=400, detail="合同未解析出迟到、早退、漏打卡扣款细则，不能启用")
        if payload.is_active:
            conn.execute(
                "UPDATE project_contracts SET is_active=0,status='inactive',updated_at=? WHERE project_name=? AND IFNULL(business_type,'')=IFNULL(?, '') AND service_type=?",
                (now, row["project_name"], row["business_type"] or "", row["service_type"]),
            )
        conn.execute(
            "UPDATE project_contracts SET is_active=?,status=?,updated_at=? WHERE id=?",
            (1 if payload.is_active else 0, "active" if payload.is_active else "inactive", now, contract_id),
        )
        # 启用合同时同步更新Rule Center规则中心的规则摘要
        if payload.is_active:
            upsert_rule_center(conn, row["project_name"], row["project_code"], row["business_type"], row["service_type"], contract_id, rules)
        updated = conn.execute("SELECT * FROM project_contracts WHERE id=?", (contract_id,)).fetchone()
        return contract_to_dict(updated)

@router.put("/contracts/{contract_id}/manual-rules")
def update_manual_rules(contract_id: int, payload: ManualRulesUpdate):
    """手动填写/编辑合同扣款细则。合同解析失败时可用此接口手动补充。"""
    now = now_text()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM project_contracts WHERE id=?", (contract_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="合同不存在")
        rules = json_loads(row["rules_json"], {})
        # 更新非None字段
        update_data = payload.model_dump(exclude_none=True)
        for key, value in update_data.items():
            rules[key] = value
        # 检查是否满足启用条件
        has_late_early = "late_early_tiers" in rules or ("late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules)
        has_required = has_late_early and "missing_clock_deduction" in rules
        new_status = "active" if has_required else "parse_failed"
        conn.execute(
            "UPDATE project_contracts SET rules_json=?, status=?, updated_at=? WHERE id=?",
            (json_dumps(rules), new_status, now, contract_id),
        )
        # 同步更新Rule Center规则中心的规则摘要
        upsert_rule_center(conn, row["project_name"], row["project_code"], row["business_type"], row["service_type"], contract_id, rules)
        updated = conn.execute("SELECT * FROM project_contracts WHERE id=?", (contract_id,)).fetchone()
        return contract_to_dict(updated)

@router.post("/contracts/reparse-all")
def reparse_all_contracts(include_active: bool = False):
    """批量重新解析合同，用最新的OCR纠错逻辑重新提取规则。
    include_active=true 时也重新解析已启用的合同（用于更新系数等规则）。
    """
    from app.core.database import get_conn, now_text
    # 第一步：读取所有需要解析的合同信息，然后关闭连接
    with get_conn() as conn:
        if include_active:
            rows = conn.execute(
                "SELECT id, project_name, business_type, contract_name, storage_path, original_name, is_active, service_type FROM project_contracts ORDER BY id"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, project_name, business_type, contract_name, storage_path, original_name, is_active, service_type FROM project_contracts WHERE status='parse_failed' ORDER BY id"
            ).fetchall()
    # 转为普通dict，避免Row对象依赖已关闭的连接
    contracts_list = [dict(r) for r in rows]

    # 第二步：逐个解析合同（不持有数据库连接，避免锁）
    results = []
    for row in contracts_list:
        storage_path = Path(row["storage_path"])
        if not storage_path.exists():
            results.append({"id": row["id"], "project_name": row["project_name"], "status": "skip", "reason": "文件不存在"})
            continue
        try:
            extracted = extract_contract_metadata(storage_path, row["original_name"])
            rules = {}
            raw_rules = extracted.get("rules", {})
            for key in ["late_early_tiers", "late_early_over_minutes_as_absence", "missing_clock_free_times_per_month", "missing_clock_free_requires_attendance_proof"]:
                if key in raw_rules:
                    rules[key] = raw_rules[key]
            for key in ["late_deduction_per_minute", "early_leave_deduction_per_minute", "missing_clock_deduction", "single_person_daily_cap", "contract_deduction_coefficient"]:
                val = raw_rules.get(key)
                if val is not None and str(val).strip():
                    try:
                        rules[key] = float(val)
                    except (ValueError, TypeError):
                        pass
            has_late_early = "late_early_tiers" in rules or ("late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules)
            has_required = has_late_early and "missing_clock_deduction" in rules
            new_status = "active" if has_required else "parse_failed"
            # 第三步：单独打开连接写入结果
            with get_conn() as conn:
                now = now_text()
                conn.execute(
                    "UPDATE project_contracts SET rules_json=?, status=?, updated_at=? WHERE id=?",
                    (json_dumps(rules), new_status, now, row["id"]),
                )
                # 同步更新Rule Center规则中心的规则摘要
                if new_status == "active":
                    upsert_rule_center(conn, row["project_name"], row.get("project_code", ""), row["business_type"], row["service_type"], row["id"], rules)
            results.append({
                "id": row["id"],
                "project_name": row["project_name"],
                "business_type": row["business_type"],
                "contract_name": row["contract_name"],
                "status": new_status,
                "rules_keys": list(rules.keys()),
            })
        except Exception as e:
            results.append({"id": row["id"], "project_name": row["project_name"], "status": "error", "reason": str(e)})
    return {"total": len(results), "results": results}

def find_active_contract(project_info: dict, service_type: str = "保洁") -> dict | None:
    project_name = str(project_info.get("项目名称") or "").strip()
    project_code = str(project_info.get("项目编码") or "").strip()
    business_type = str(project_info.get("业态") or project_info.get("项目属性") or "").strip()
    with get_conn() as conn:
        row = None
        if project_code and business_type:
            row = conn.execute(
                "SELECT * FROM project_contracts WHERE is_active=1 AND service_type=? AND project_code=? AND business_type=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                (service_type, project_code, business_type),
            ).fetchone()
        if not row and project_name and business_type:
            row = conn.execute(
                "SELECT * FROM project_contracts WHERE is_active=1 AND service_type=? AND project_name=? AND business_type=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                (service_type, project_name, business_type),
            ).fetchone()
        if not row and project_code:
            row = conn.execute(
                "SELECT * FROM project_contracts WHERE is_active=1 AND service_type=? AND project_code=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                (service_type, project_code),
            ).fetchone()
        if not row and project_name:
            row = conn.execute(
                "SELECT * FROM project_contracts WHERE is_active=1 AND service_type=? AND project_name=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                (service_type, project_name),
            ).fetchone()
        return contract_to_dict(row) if row else None

def apply_contract_rules(configs: dict, contract: dict | None) -> dict:
    if not contract:
        raise ValueError("未匹配到项目启用合同，无法按合同扣款规则审核。请先在系统配置上传并成功解析合同。")
    rules = contract.get("rules", {})
    has_late_early = "late_early_tiers" in rules or ("late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules)
    missing = []
    if not has_late_early:
        missing.append("迟到/早退扣款")
    if "missing_clock_deduction" not in rules:
        missing.append("漏打卡扣款")
    if missing:
        raise ValueError("项目合同未解析出迟到、早退、漏打卡扣款细则，不能启用审核。请上传包含清晰扣款条款的合同。")
    updated = dict(configs)
    for key, value in rules.items():
        if key in CONTRACT_RULE_KEYS and value not in ("", None):
            updated[key] = value if isinstance(value, (list, bool)) else float(value)
    return updated

def rule_center_to_dict(row) -> dict:
    item = dict(row)
    item["rules"] = json_loads(item.pop("rules_json", None), {})
    return item

def upsert_rule_center(conn, project_name: str, project_code: str, business_type: str, service_type: str, contract_id: int, rules: dict):
    if not project_name or not service_type or not rules:
        return
    now = now_text()
    row = conn.execute(
        """
        SELECT * FROM project_rule_center
        WHERE project_name=? AND IFNULL(project_code,'')=IFNULL(?, '') AND IFNULL(business_type,'')=IFNULL(?, '') AND service_type=?
        ORDER BY id DESC LIMIT 1
        """,
        (project_name, project_code or "", business_type or "", service_type),
    ).fetchone()
    version_label = "V1"
    if row:
        match = re.search(r"V(\d+)", row["version_label"] or "V1", re.I)
        version_label = f"V{int(match.group(1)) + 1}" if match else "V2"
    conn.execute(
        """
        INSERT INTO project_rule_center(project_name,project_code,business_type,service_type,contract_id,rules_json,status,version_label,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (project_name, project_code or "", business_type or "", service_type, contract_id, json_dumps(rules), "待确认", version_label, now, now),
    )
    conn.execute(
        """
        INSERT INTO project_statuses(project_name,project_code,business_type,contract_status,schedule_status,audit_status,rectification_status,upload_time,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT DO NOTHING
        """,
        (project_name, project_code or "", business_type or "", "已上传", "待上传", "待上传", "未整改", now, now),
    )

def extract_contract_metadata(path: Path, original_name: str) -> dict:
    text = extract_contract_text(path)
    source = f"{Path(original_name).stem}\n{text}"
    return {
        "project_name": extract_project_name(source),
        "project_code": extract_first(source, [r"项目编码[:：\s]*([A-Za-z0-9_-]+)"]),
        "business_type": extract_business_type(source),
        "supplier": extract_supplier(source),
        "contract_no": extract_first(source, [r"(?:合同编号|合同号)[:：\s]*([A-Za-z0-9_\-（）()第号]+)"]),
        "contract_name": Path(original_name).stem,
        "service_type": "保洁" if "保洁" in source else ("保安" if "保安" in source else "保洁"),
        "version": extract_first(source, [r"版本[:：\s]*([A-Za-z0-9_\-\.]+)"]),
        "start_date": normalize_date_text(extract_first(source, [r"(?:开始日期|合同开始|服务期限自|服务期自)[:：\s]*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2})"])),
        "end_date": normalize_date_text(extract_first(source, [r"(?:结束日期|合同结束|至)[:：\s]*(\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2})"])),
        "rules": extract_contract_rules(source),
    }

def extract_contract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            # 检测无效文本：长度不足、或主要是水印/加密标记（如"契约锁"）
            stripped = text.strip()
            meaningful_chars = len(stripped.replace("契约锁", "").replace(" ", "").replace("\n", "").replace("\r", ""))
            if len(stripped) < 200 or meaningful_chars < 100:
                text = ocr_pdf_text(path)
            return text
        if suffix == ".docx":
            return extract_docx_text(path)
    except Exception:
        return ""
    return ""

def ocr_pdf_text(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
        import pytesseract
        import shutil
        # 优先使用系统 PATH 中的 tesseract；回退到常见路径
        tesseract_cmd = shutil.which("tesseract")
        if not tesseract_cmd:
            for candidate in [r"/usr/bin/tesseract", r"C:\Users\Administrator\AppData\Roaming\TRAE SOLO CN\ModularData\ai-agent\vm\tools\bin\tesseract.cmd"]:
                if Path(candidate).exists():
                    tesseract_cmd = candidate
                    break
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        pdf = pdfium.PdfDocument(str(path))
        texts = []
        for index in range(len(pdf)):
            page = pdf[index]
            image = page.render(scale=2.0).to_pil()
            texts.append(pytesseract.image_to_string(image, lang="chi_sim", config="--psm 6"))
        return "\n".join(texts)
    except Exception:
        return ""

def extract_docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", ns):
        texts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
        if texts:
            paragraphs.append("".join(texts))
    return "\n".join(paragraphs)

def extract_project_name(text: str) -> str:
    explicit = extract_first(text, [
        r"项目名称[:：\s]*([^\n\r，,。；;]{2,50})",
        r"项目[:：\s]*([^\n\r，,。；;]{2,50})",
    ])
    if explicit:
        return cleanup_project_name(explicit)
    match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}(?:项目|广场|中心|大厦|园区|小区|天地))", text)
    return cleanup_project_name(match.group(1)) if match else ""

def cleanup_project_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"(合同|协议|保洁|保安|服务|外包|考勤|扣款).*$", "", text).strip(" -_（）()")
    return text[:50]

def extract_business_type(text: str) -> str:
    value = extract_first(text, [
        r"(?:项目属性|业态|业务类型)[:：\s]*([^\n\r，,。；;]{1,12})",
    ])
    return normalize_business_type_label(value)

def normalize_business_type_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "商酒" in text:
        return "商业"
    if text in {"商", "商场"} or "商业" in text:
        return "商业"
    if text == "住" or "住宅" in text:
        return "住宅"
    if "写字楼" in text or "办公" in text:
        return "写字楼"
    if "酒店" in text:
        return "酒店"
    if "街区" in text or "外场" in text:
        return "街区"
    return text

def extract_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""

def extract_supplier(text: str) -> str:
    """提取乙方/供应商名称，要求以公司后缀结尾，避免OCR乱码。"""
    company_suffixes = ["有限公司", "股份公司", "有限责任公司", "集团", "实业", "保洁服务部"]
    patterns = [
        r"(?:乙方|供应商|承包方|服务单位|乙方名称)[:：\s]*([^\n\r，,。；;]{2,60})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = match.group(1).strip()
            # 必须包含公司后缀
            if any(suffix in candidate for suffix in company_suffixes):
                # 清理：截取到公司后缀为止
                for suffix in company_suffixes:
                    if suffix in candidate:
                        idx = candidate.index(suffix) + len(suffix)
                        candidate = candidate[:idx]
                        break
                # 长度合理性检查
                if 4 <= len(candidate) <= 40:
                    return candidate
    return ""

def normalize_date_text(value: str) -> str:
    text = str(value or "").replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"

def extract_contract_rules(text: str) -> dict:
    normalized = normalize_rule_text(text)
    rules = {}

    # === 迟到/早退分档扣款 ===
    # 策略1: 正则匹配三档（≤30分钟、≤60分钟、>60分钟按缺勤）
    tier_30_60 = re.search(
        r"迟到或早退30分[钟铁种]以内(?:[（(]包括30分钟?[）)》。]?)?"
        r"扣除(?:标准|标淮)[为:：,，]*(\d+(?:\.\d+)?)元/[次汀江]"
        r".{0,10}?迟到或早退[!1一]小时以内(?:[（(]包括[!1一]?小时?[）)》。]?)?"
        r"扣除(?:标准|标淮)[为:：,，]*(\d+(?:\.\d+)?)元/[次汀江]"
        r".{0,50}?超过[^。；;]{0,30}?1小时按缺勤处理",
        normalized,
    )
    if tier_30_60:
        rules["late_early_tiers"] = [
            {"max_minutes": 30, "amount": float(tier_30_60.group(1))},
            {"max_minutes": 60, "amount": float(tier_30_60.group(2))},
        ]
        rules["late_early_over_minutes_as_absence"] = 60
    else:
        # 策略2: 正则匹配两档（≤30分钟、>30分钟按缺勤）
        tier_30_only = re.search(
            r"迟到或早退(?:30分[钟铁种]|半小[时])以内(?:[（(]包括(?:30分[钟铁种]?|半小[时]?)[）)》。]?)?"
            r"扣除(?:标准|标淮)[为:：,，E]{0,3}(\d+(?:\.\d+)?)\s*元/[次汀江]"
            r".{0,60}?超过[^。；;]{0,30}?(?:半小[时]|30分[钟铁种])按缺勤处理",
            normalized,
        )
        if tier_30_only:
            rules["late_early_tiers"] = [
                {"max_minutes": 30, "amount": float(tier_30_only.group(1))},
            ]
            rules["late_early_over_minutes_as_absence"] = 30
        else:
            # 策略3: 模糊匹配 - 找"迟到"+"扣除"+"元/次"附近的数字
            fuzzy_tier = fuzzy_extract_late_early_tier(normalized)
            if fuzzy_tier:
                rules["late_early_tiers"] = fuzzy_tier["tiers"]
                rules["late_early_over_minutes_as_absence"] = fuzzy_tier["over_minutes"]

    # === 迟到/早退每分钟扣款（非分档格式）===
    late = re.search(r"迟到[^。；;\n\r]{0,80}?(?:每(?:分钟|分)|按分钟|/分钟|每分钟扣)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*元", normalized)
    if late:
        rules["late_deduction_per_minute"] = late.group(1)
    early = re.search(r"早退[^。；;\n\r]{0,80}?(?:每(?:分钟|分)|按分钟|/分钟|每分钟扣)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*元", normalized)
    if early:
        rules["early_leave_deduction_per_minute"] = early.group(1)

    # === 漏打卡扣款 ===
    # 策略1: "超过X次，扣除标准Y元/人次"
    missing_free = re.search(r"每人每月累计(?:漏打卡|未打卡|缺卡)次数超过(\d+)次,?扣除标准[为:：,，]*(\d+(?:\.\d+)?)元/人次", normalized)
    if missing_free:
        rules["missing_clock_free_times_per_month"] = float(missing_free.group(1))
        rules["missing_clock_deduction"] = missing_free.group(2)
    # 策略2: 模糊匹配 - 找"漏打卡"+"元"附近的数字
    if "missing_clock_deduction" not in rules:
        fuzzy_missing = fuzzy_extract_missing_clock_deduction(normalized)
        if fuzzy_missing:
            rules["missing_clock_deduction"] = fuzzy_missing
    # 漏打卡免扣次数 + 需要证明
    if "missing_clock_free_times_per_month" not in rules:
        free_match = re.search(r"(?:前|超过)(\d+)次[^。；;]{0,30}?(?:不扣款|免扣|需提供出勤证明)", normalized)
        if free_match:
            rules["missing_clock_free_times_per_month"] = float(free_match.group(1))
    proof_required = re.search(
        r"(?:在提供有效出勤证明的前提下|有出勤(?:凭证|证明|证)的情况下)[^。；;]{0,40}(?:三次以内|两次以内|前\d+次|月度\d+次内)[^。；;]{0,20}不做扣款",
        normalized,
    )
    if proof_required:
        rules["missing_clock_free_requires_attendance_proof"] = True
    # 兜底：如果文本中同时有"漏打卡"和"出勤证明"，也设为需要证明
    if "missing_clock_free_requires_attendance_proof" not in rules:
        if "漏打卡" in normalized and "出勤证明" in normalized:
            rules["missing_clock_free_requires_attendance_proof"] = True

    # === 单人单日上限 ===
    cap = re.search(r"(?:单人单日|每日|日)[^。；;\n\r]{0,40}?上限[^0-9]{0,10}(\d+(?:\.\d+)?)\s*元", normalized)
    if cap:
        rules["single_person_daily_cap"] = cap.group(1)

    # === 缺编扣款系数 ===
    rules["contract_deduction_coefficient"] = extract_shortage_coefficient(normalized)

    # === 每日打卡次数 ===
    # 从合同文本中提取每日要求的打卡次数
    # 优先匹配"早中晚三次"等明确表述打卡要求的文字
    # 注意：不能匹配处罚条款中的"两次卡都未..."等文字，那不是打卡要求
    clock_count = None
    # 策略1: "早中晚"+"三次" → 3次（最优先，明确表示早中晚各打一次）
    if re.search(r"早[、，,]?\s*中[、，,]?\s*晚[^。；;\n\r]{0,20}?三\s*次", normalized) or \
       re.search(r"不少于[^。；;\n\r]{0,20}?三\s*次[^。；;\n\r]{0,10}?打卡", normalized) or \
       re.search(r"三\s*次[^。；;\n\r]{0,10}?早[、，,]?\s*中[、，,]?\s*晚", normalized):
        clock_count = 3
    # 策略2: "每日打卡X次" / "每天打X次卡"
    if clock_count is None:
        m = re.search(r"(?:每日|每天|日常)[^。；;\n\r]{0,15}?(?:打卡|考勤|打卡记录)\s*(\d+)\s*次", normalized)
        if m:
            clock_count = int(m.group(1))
    if clock_count is None:
        m = re.search(r"(?:每日|每天|日常)[^。；;\n\r]{0,15}?(?:打卡|考勤)\s*([二两三四五六])\s*次", normalized)
        if m and m.group(1) in {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}:
            clock_count = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}[m.group(1)]
    # 策略3: "上班时间两次卡"只在没有其他匹配时使用，且需确认是要求而非处罚
    if clock_count is None:
        m = re.search(r"(?:上班|每日|每天)[^。；;\n\r]{0,10}?(?:需|要求|应当|应该|必须)[^。；;\n\r]{0,10}?([二两三四五六])\s*次(?:卡|打卡)", normalized)
        if m and m.group(1) in {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}:
            clock_count = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}[m.group(1)]
    if clock_count is not None:
        rules["required_clock_count"] = clock_count

    return rules

def fuzzy_extract_late_early_tier(normalized: str) -> dict | None:
    """模糊匹配迟到/早退分档规则。
    策略：在"迟到"关键词附近找"扣除"+"元/次"的数字。
    """
    # 找到所有"迟到或早退"或"迟到"的位置
    keyword_positions = [m.start() for m in re.finditer(r"迟到或早退|迟到", normalized)]
    if not keyword_positions:
        return None

    tiers = []
    over_minutes = None

    for pos in keyword_positions:
        # 取关键词后200字符的上下文
        context = normalized[pos:pos + 200]
        # 在上下文中找"30分钟"或"半小时" + "扣除" + 数字 + "元/次"
        match_30 = re.search(r"(?:30分[钟铁种]|半小[时]).{0,20}?扣除.{0,5}?(\d+(?:\.\d+)?)\s*元/[次汀江]", context)
        if match_30:
            amount = float(match_30.group(1))
            # 避免重复添加
            if not any(t["max_minutes"] == 30 for t in tiers):
                tiers.append({"max_minutes": 30, "amount": amount})
        # 找"1小时"或"60分钟" + "扣除" + 数字 + "元/次"
        match_60 = re.search(r"(?:[!1一]小时|60分[钟铁种]).{0,20}?扣除.{0,5}?(\d+(?:\.\d+)?)\s*元/[次汀江]", context)
        if match_60:
            amount = float(match_60.group(1))
            if not any(t["max_minutes"] == 60 for t in tiers):
                tiers.append({"max_minutes": 60, "amount": amount})
        # 找"超过" + "1小时"/"半小时"/"30分钟" + "按缺勤"
        match_over = re.search(r"超过.{0,10}?(?:[!1一]小时|半小[时]|30分[钟铁种]).{0,10}?按缺勤", context)
        if match_over:
            if "1小时" in match_over.group(0) or "一小时" in match_over.group(0):
                over_minutes = 60
            elif "半小" in match_over.group(0) or "30分" in match_over.group(0):
                over_minutes = 30

    if not tiers:
        return None
    if over_minutes is None:
        # 默认：有60分钟档则>60按缺勤，只有30分钟档则>30按缺勤
        over_minutes = 60 if any(t["max_minutes"] == 60 for t in tiers) else 30
    return {"tiers": tiers, "over_minutes": over_minutes}

def fuzzy_extract_missing_clock_deduction(normalized: str) -> str | None:
    """模糊匹配漏打卡扣款金额。
    策略：在"漏打卡"关键词附近找"元"前面的数字。
    """
    for m in re.finditer(r"漏打卡|未打卡|缺卡", normalized):
        pos = m.start()
        context = normalized[pos:pos + 100]
        # 找"X元/人次"或"X元"
        match = re.search(r"(\d+(?:\.\d+)?)\s*元(?:/人次)?", context)
        if match:
            return match.group(1)
    return None

def extract_shortage_coefficient(normalized: str) -> str | None:
    """从合同文本中提取缺编扣款系数。
    合同原文格式：工时单价*1.2*缺勤总时长
    OCR常见错误：
      - 工时单价*124缺勤总时长（*1.2*→*124，丢失小数点和*）
      - 工时单价41,24缺勤总时长（*→4，1.2→1,2）
      - 工时单价*1.2#缺勤总时长（*→#）
      - 工时单价*1.2缺勤总时长（正常但缺第二个*）
    """
    for m in re.finditer(r"工时单价([^。；;]{0,30}?)(?:缺勤|铁勤)总时长", normalized):
        middle = m.group(1)
        # 预处理：OCR常把第二个*识别为4，如果middle以4结尾且前面是数字，去掉末尾4
        # 例如: *1,24 → *1,2（4是*）, *124 → *12（4是*）
        middle_clean = re.sub(r'(\d)4$', r'\1', middle)
        # 也处理开头4（第一个*被OCR为4）: 41,24 → 1,2
        middle_clean = re.sub(r'^4(\d)', r'\1', middle_clean)

        # 情况1: *1.2* / *1.2# / *1.2 → 直接取小数
        match = re.search(r"[\*#]?\s*(\d+[.,，。]\d+)\s*[\*#]?", middle_clean)
        if match:
            val = match.group(1).replace(",", ".").replace("，", ".").replace("。", ".")
            return val
        # 情况2: *12 → 1.2（两位数以1开头，小数点丢失）或 *125 → 1.25（三位数）
        match = re.search(r"[\*#](1\d{1,2})(?!\d)", middle_clean)
        if match:
            val = match.group(1)
            return f"{val[0]}.{val[1:]}"
        # 情况3: 纯数字如 *1 或 *2
        match = re.search(r"[\*#]?\s*(\d)\s*[\*#]?", middle_clean)
        if match:
            return match.group(1)
    return None

def normalize_shortage_coefficient(value: str, context: str) -> str:
    text = str(value or "").strip().replace(",", ".").replace("，", ".").replace("。", ".")
    # 合同原式为"工时单价*1.2*缺勤总时长"，OCR 常把第二个"*"识别为"4"，得到"1.24缺勤总时长"。
    if text == "1.24" and re.search(r"工时单价[^。；;]{0,30}1[\.,，。]24(?:缺勤|铁勤)总时长", context):
        return "1.2"
    return text

def normalize_rule_text(text: str) -> str:
    """标准化合同文本：去空格 + 全量OCR纠错。
    采用三层纠错策略，覆盖契约锁加密PDF的OCR常见错误。
    """
    value = str(text or "")
    value = re.sub(r"\s+", "", value)

    # 1. 全量替换字典（精确匹配）
    replacements = {
        "O": "0", "o": "0", "￥": "元", "／": "/", "—": "-", "－": "-",
        "每分种": "每分钟", "迟倒": "迟到", "旱退": "早退",
        "分铁": "分钟", "包揪": "包括", "扒除": "扣除", "抚除": "扣除",
        "速约": "违约", "银岗": "缺岗", "铁勤": "缺勤", "标淮": "标准",
        "早逾": "早退", "溥打卡": "漏打卡", "漪打卡": "漏打卡",
        "汀": "次", "江": "次", "逾": "退",
        # 契约锁加密PDF的OCR错误
        "武早逆": "或早退", "早迹": "早退", "早追": "早退",
        "扣院": "扣除", "扣院标准": "扣除标准",
        "不敏)": "不做", "不敏）": "不做",
        "湘打卡": "漏打卡", "漾打卡": "漏打卡",
        "缺门": "缺岗", "跌勤": "缺勤", "狒勤": "缺勤",
        "工时单价#": "工时单价*", "单价#": "单价*",
        "单价*019": "单价*0.1*9", "单价*0.1*9在岗": "单价*1在岗",
        # 新增OCR错误（江都文昌华府合同）
        "湖打卡": "漏打卡", "渑打卡": "漏打卡", "湾打卡": "漏打卡",
        "缺勇总时长": "缺勤总时长", "缺勒总时长": "缺勤总时长",
        "包拾": "包括", "包芸": "包括",
        "元7欣": "元/次", "元/欣": "元/次",
        "早迟": "早退", "早迫": "早退",
        "迟则": "迟到", "扣陈": "扣除",
        "扬款": "扣款", "扣院标准为": "扣除标准为",
        "魅过": "超过", "技缺": "按缺",
        "缺勒处理": "缺勤处理", "缺勤处理": "缺勤处理",
        "丁做": "不做", "祝荣": "累计",
        "渑打卡": "漏打卡", "计渑": "计漏",
        # 金鹰花园合同OCR错误
        "缺勤盐时长": "缺勤总时长", "缺盐时长": "缺勤总时长",
        "铧勤": "缺勤", "铧岗": "缺岗",
        "挂铧勤处理": "按缺勤处理",
        "返到": "迟到", "早遏": "早退",
        "分钝": "分钟",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    # 2. 模糊纠错：关键词附近用正则修复OCR乱码
    value = re.sub(r'包[^括]{0,5}括', '包括', value)
    value = value.replace("超过!小时", "超过1小时").replace("超过!小", "超过1小")
    # "迟到X早Y" 中 X∈{武,或,戊,戌,则} Y∈{逆,退,迹,追,逾,迟,迫} → "迟到或早退"
    value = re.sub(r'迟到[武或戊戌则]早[逆退迹追逾迟迫]', '迟到或早退', value)
    # "扣Z标准" Z∈{院,陈,降,险,陈} → "扣除标准"
    value = re.sub(r'扣[院陈降险]标准', '扣除标准', value)
    # "C打卡" C∈{湘,漾,溥,漪,漏,湖,渑,湾} → "漏打卡"
    value = re.sub(r'[湘漾溥漪湖渑湾]打卡', '漏打卡', value)
    # "D勤" D∈{跌,狒,铁,勇} → "缺勤"
    value = re.sub(r'[跌狒铁勇]勤', '缺勤', value)
    # "D总时长" D∈{勇,勒,盐} → "缺勤总时长"
    value = re.sub(r'(?:缺)?[勇勒盐]总时长', '缺勤总时长', value)
    # "X勤" X∈{铧,铁,跌,狒} → "缺勤"
    value = re.sub(r'[铧铁跌狒]勤', '缺勤', value)
    # "X岗" X∈{铧,银} → "缺岗"
    value = re.sub(r'[铧银]岗', '缺岗', value)
    # "挂X勤处理" → "按缺勤处理"
    value = re.sub(r'挂[铧铁]?勤处理', '按缺勤处理', value)
    # "返到" → "迟到", "早遏" → "早退"
    value = value.replace("返到", "迟到").replace("早遏", "早退")
    # "分钝" → "分钟"
    value = value.replace("分钝", "分钟")
    # "银岗" → "缺岗"
    value = value.replace("银岗", "缺岗")
    # "扣Z标准为" Z∈{陈,院,降,险} → "扣除标准为"
    value = re.sub(r'扣[陈院降险]标准为', '扣除标准为', value)
    # "丁做" → "不做"
    value = value.replace("丁做", "不做")
    # "扬款" → "扣款"
    value = value.replace("扬款", "扣款")
    # "元Y欣" Y∈{7,/} → "元/次"
    value = re.sub(r'元[7/]欣', '元/次', value)
    # "魅过" → "超过"
    value = value.replace("魅过", "超过")
    # "技缺勒处理" → "按缺勤处理"
    value = value.replace("技缺勒处理", "按缺勤处理").replace("技缺勤处理", "按缺勤处理")

    return value
