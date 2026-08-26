from pathlib import Path
import re
from urllib.parse import unquote

from fastapi import APIRouter, Header

from app.core.config import settings
from app.core.database import get_conn, now_text
from app.services.rule_engine import normalize_business_type

router = APIRouter()

def normalize_role(value: str) -> str:
    value = unquote(str(value or ""))
    return "项目账号" if value in {"项目账号", "project_user"} else "集团管理员"

def decode_header_value(value: str) -> str:
    return unquote(str(value or ""))

@router.get("/management/projects")
def list_project_management(x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    role = normalize_role(x_user_role)
    project = decode_header_value(x_project_name)
    with get_conn() as conn:
        master_rows = conn.execute(
            """
            SELECT * FROM project_business_types
            WHERE status='启用'
            ORDER BY project_name,business_type
            """
        ).fetchall()
        status_rows = conn.execute(
            """
            SELECT * FROM project_statuses
            ORDER BY updated_at DESC,id DESC
            """
        ).fetchall()
        batch_rows = conn.execute(
            """
            SELECT project_name,project_code,business_type,status,created_at,finished_at
            FROM audit_batches
            WHERE project_name IS NOT NULL AND project_name!=''
            ORDER BY id DESC
            """
        ).fetchall()
        contract_rows = conn.execute(
            """
            SELECT project_name,project_code,business_type,service_type,
                   SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active_count,
                   COUNT(*) AS contract_count
            FROM project_contracts
            WHERE project_name IS NOT NULL AND project_name!=''
            GROUP BY project_name,project_code,business_type,service_type
            """
        ).fetchall()
    status_map = {}
    for row in status_rows:
        key = (row["project_name"], row["business_type"] or "")
        if key not in status_map:
            status_map[key] = dict(row)
    contract_map = {
        (row["project_name"], row["business_type"] or ""): dict(row)
        for row in contract_rows
    }
    project_level_contract_map = {
        row["project_name"]: dict(row)
        for row in contract_rows
        if not (row["business_type"] or "")
    }
    # 按项目+业态+服务类型分组的合同状态
    contract_service_map = {}
    for row in contract_rows:
        key = (row["project_name"], row["business_type"] or "", row["service_type"] or "")
        if key not in contract_service_map:
            contract_service_map[key] = dict(row)
    batch_map = {}
    for row in batch_rows:
        key = (row["project_name"], row["business_type"] or "")
        if key not in batch_map:
            batch_map[key] = dict(row)
    result = []
    for master in master_rows:
        if role == "项目账号" and project and master["project_name"] != project:
            continue
        key = (master["project_name"], master["business_type"])
        status = status_map.get(key, {})
        contract = contract_map.get(key) or project_level_contract_map.get(master["project_name"], {})
        batch = batch_map.get(key) or batch_map.get((master["project_name"], ""), {})
        contract_status = status.get("contract_status")
        if not contract_status:
            contract_status = "已上传" if contract.get("contract_count") and contract.get("business_type") else ("已上传（未分业态）" if contract.get("contract_count") else "待上传")
        schedule_status = status.get("schedule_status") or ("已上传" if batch else "待上传")
        audit_status = status.get("audit_status") or (normalize_audit_status(batch.get("status", "")) if batch else "待上传")

        # 获取保安/保洁合同状态
        security_contract = contract_service_map.get((master["project_name"], master["business_type"], "保安"), {})
        cleaning_contract = contract_service_map.get((master["project_name"], master["business_type"], "保洁"), {})
        security_contract_status = "待上传" if not security_contract.get("contract_count") else ("已启用" if security_contract.get("active_count") else "已上传")
        cleaning_contract_status = "待上传" if not cleaning_contract.get("contract_count") else ("已启用" if cleaning_contract.get("active_count") else "已上传")

        # 保安/保洁排班状态：有合同才显示排班状态，无合同显示"—"
        has_security_contract = bool(security_contract.get("contract_count"))
        has_cleaning_contract = bool(cleaning_contract.get("contract_count"))
        security_schedule_status = schedule_status if has_security_contract else "—"
        cleaning_schedule_status = schedule_status if has_cleaning_contract else "—"
        # 保安/保洁审核状态：有合同才显示审核状态，无合同显示"—"
        security_audit_status = audit_status if has_security_contract else "—"
        cleaning_audit_status = audit_status if has_cleaning_contract else "—"

        # 保安/保洁审核完成时间：审核完成且有对应合同才显示批次完成时间，否则为空
        batch_finished = batch.get("finished_at") or "" if batch else ""
        security_audit_time = batch_finished if (has_security_contract and audit_status == "审核完成") else ""
        cleaning_audit_time = batch_finished if (has_cleaning_contract and audit_status == "审核完成") else ""

        result.append({
            "project_name": master["project_name"],
            "project_code": master["project_code"] or "",
            "business_type": master["business_type"],
            "contract_status": contract_status,
            "security_contract_status": security_contract_status,
            "cleaning_contract_status": cleaning_contract_status,
            "schedule_status": schedule_status,
            "security_schedule_status": security_schedule_status,
            "cleaning_schedule_status": cleaning_schedule_status,
            "audit_status": audit_status,
            "security_audit_status": security_audit_status,
            "cleaning_audit_status": cleaning_audit_status,
            "rectification_status": status.get("rectification_status") or ("待确认" if audit_status == "审核完成" else "未整改"),
            "security_audit_time": security_audit_time,
            "cleaning_audit_time": cleaning_audit_time,
            "updated_at": status.get("updated_at") or (batch.get("finished_at") or batch.get("created_at") if batch else master["updated_at"]),
        })
    return result

@router.get("/management/project-master")
def list_project_master(x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    role = normalize_role(x_user_role)
    project = decode_header_value(x_project_name)
    with get_conn() as conn:
        if role == "项目账号" and project:
            rows = conn.execute(
                "SELECT * FROM project_business_types WHERE status='启用' AND project_name=? ORDER BY project_name,business_type",
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM project_business_types WHERE status='启用' ORDER BY project_name,business_type"
            ).fetchall()
    return [dict(row) for row in rows]

def normalize_audit_status(status: str) -> str:
    return {
        "created": "待上传",
        "uploaded": "待审核",
        "validated": "待审核",
        "running": "审核中",
        "completed": "审核完成",
        "failed": "审核失败",
        "validation_failed": "校验失败",
    }.get(status, status)

@router.get("/management/bi-sync")
def bi_sync_status(project_name: str | None = None, audit_month: str | None = None):
    records = scan_bi_data(project_name=project_name, audit_month=audit_month)
    with get_conn() as conn:
        for item in records:
            exists = conn.execute("SELECT id FROM bi_sync_records WHERE storage_path=?", (item["storage_path"],)).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO bi_sync_records(project_name,project_code,audit_month,business_type,file_name,storage_path,sync_status,synced_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    """,
                    (
                        item.get("project_name", ""),
                        item.get("project_code", ""),
                        item.get("audit_month", ""),
                        item.get("business_type", ""),
                        item.get("file_name", ""),
                        item.get("storage_path", ""),
                        "已同步",
                        item.get("synced_at", now_text()),
                    ),
                )
    return records

def scan_bi_data(project_name: str | None = None, audit_month: str | None = None) -> list[dict]:
    settings.bi_data_dir.mkdir(parents=True, exist_ok=True)
    result = []
    month_key = normalize_month_for_match(audit_month or "")

    # 计算上一个月的匹配键（BI导出通常是上月数据）
    prev_month_key = ""
    if audit_month and "-" in str(audit_month):
        parts = str(audit_month).split("-")
        y, m = int(parts[0]), int(parts[1])
        prev_m = m - 1 if m > 1 else 12
        prev_y = y if m > 1 else y - 1
        prev_month_key = normalize_month_for_match(f"{prev_y}-{prev_m:02d}")

    for path in settings.bi_data_dir.glob("**/*"):
        if path.suffix.lower() not in {".xlsx", ".csv"}:
            continue
        name = path.name
        name_normalized = normalize_month_for_match(name)
        if project_name and project_name not in name:
            continue
        # 按当月或上月匹配
        if month_key and month_key not in name_normalized and prev_month_key and prev_month_key not in name_normalized:
            continue
        result.append({
            "project_name": infer_project_name_from_bi_name(name),
            "project_code": "",
            "audit_month": infer_month_from_name(name),
            "business_type": infer_business_type_from_name(name),
            "file_name": name,
            "storage_path": str(path),
            "sync_status": "已同步",
            "synced_at": now_text(),
        })
    return sorted(result, key=lambda item: item["file_name"])

def infer_business_type_from_name(name: str) -> str:
    return normalize_business_type(name)

def infer_month_from_name(name: str) -> str:
    match = re.search(r"(20\d{2})[-年._]?(\d{1,2})", name)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"
    match = re.search(r"(\d{1,2})月", name)
    if match:
        return f"{now_text()[:4]}-{int(match.group(1)):02d}"
    return ""

def normalize_month_for_match(value: str) -> str:
    text = str(value or "")
    match = re.search(r"(20\d{2})[-年._]?(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}{int(match.group(2)):02d}"
    return re.sub(r"\D", "", text)

def infer_project_name_from_bi_name(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"BI|考勤|物业外包考勤表|\d{4}[-年._]?\d{1,2}月?", "", stem, flags=re.I)
    stem = re.sub(r"[+_（）()\\-]+", " ", stem).strip()
    return stem
