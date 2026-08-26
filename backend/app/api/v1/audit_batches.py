from pathlib import Path
import re
from urllib.parse import unquote
from fastapi import APIRouter, UploadFile, File, HTTPException, Header, BackgroundTasks
from typing import List
from pydantic import BaseModel

from app.core.config import settings
from app.core.database import get_conn, now_text, json_dumps, json_loads
from app.services.excel_parser import validate_project_workbook
from app.services.rule_engine import run_audit

router = APIRouter()

# 正在审核中的批次集合（内存级锁，防止同一批次被重复审核）
_auditing_batches: set[int] = set()

def normalize_role(value: str) -> str:
    value = unquote(str(value or ""))
    return "项目账号" if value in {"项目账号", "project_user"} else "集团管理员"

def decode_header_value(value: str) -> str:
    return unquote(str(value or ""))

def ensure_version_table(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_result_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_batch_id INTEGER NOT NULL,
            version_label TEXT NOT NULL,
            summary_json TEXT,
            results_json TEXT,
            ai_analysis TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

class AuditBatchCreate(BaseModel):
    project_name: str = ""
    project_code: str = ""
    audit_month: str = ""
    business_type: str = ""

@router.post("/audit-batches")
def create_audit_batch(payload: AuditBatchCreate | None = None):
    payload = payload or AuditBatchCreate()
    with get_conn() as conn:
        # 确保 business_type 列存在
        _ensure_batch_columns(conn)
        cur = conn.execute(
            "INSERT INTO audit_batches(project_name,project_code,audit_month,business_type,status, progress, message, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (payload.project_name, payload.project_code, payload.audit_month, payload.business_type, "待上传", 0, "审核批次已创建，待上传资料", now_text()),
        )
        upsert_project_status(conn, payload.project_name, payload.project_code, audit_status="待上传")
        return {"id": cur.lastrowid, "status": "created", "progress": 0}


def _ensure_batch_columns(conn):
    """确保 audit_batches 表有 business_type 列。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(audit_batches)").fetchall()]
    if "business_type" not in cols:
        conn.execute("ALTER TABLE audit_batches ADD COLUMN business_type TEXT DEFAULT ''")

@router.post("/audit-batches/{batch_id}/upload")
async def upload_files(
    batch_id: int,
    project_file: UploadFile = File(...),
    attendance_files: List[UploadFile] = File(...),
):
    if not project_file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="项目基础资料仅支持 .xlsx 文件")
    if not attendance_files:
        raise HTTPException(status_code=400, detail="请至少上传一个BI考勤文件")
    for file in attendance_files:
        lower = file.filename.lower()
        if not (lower.endswith(".xlsx") or lower.endswith(".csv")):
            raise HTTPException(status_code=400, detail="BI考勤仅支持 .xlsx 或 .csv 文件")

    batch_dir = Path(settings.upload_dir) / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    project_path = batch_dir / "项目基础资料.xlsx"
    project_path.write_bytes(await project_file.read())
    attendance_records = []
    for index, file in enumerate(attendance_files, start=1):
        original_name = Path(file.filename).name
        safe_original_name = re.sub(r'[\\/:*?"<>|]', "_", original_name)
        attendance_path = batch_dir / f"BI考勤_{index}_{safe_original_name}"
        attendance_path.write_bytes(await file.read())
        attendance_records.append((batch_id, "bi_attendance", file.filename, str(attendance_path), now_text()))

    with get_conn() as conn:
        conn.execute("DELETE FROM uploaded_files WHERE audit_batch_id=?", (batch_id,))
        conn.executemany(
            "INSERT INTO uploaded_files(audit_batch_id,file_type,original_name,storage_path,created_at) VALUES(?,?,?,?,?)",
            [(batch_id, "project_base", project_file.filename, str(project_path), now_text()), *attendance_records],
        )
        conn.execute(
            "UPDATE audit_batches SET status=?, progress=?, message=? WHERE id=?",
            ("待审核", 20, "文件上传完成，待审核", batch_id),
        )
        batch = conn.execute("SELECT project_name,project_code FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if batch:
            upsert_project_status(conn, batch["project_name"], batch["project_code"], schedule_status="已上传", audit_status="待审核", upload_time=now_text())
    return {"batch_id": batch_id, "status": "uploaded", "message": "上传完成"}

@router.post("/audit-batches/{batch_id}/resubmit-schedule")
async def resubmit_schedule(batch_id: int, project_file: UploadFile = File(...)):
    if not project_file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="项目基础资料仅支持 .xlsx 文件")
    with get_conn() as conn:
        batch = conn.execute("SELECT * FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        if int(batch["is_locked"] or 0):
            raise HTTPException(status_code=400, detail="最终版已确认锁定，不能重新提交排班")
        ensure_version_table(conn)
        if batch["results_json"]:
            version_count = conn.execute("SELECT COUNT(*) AS count FROM audit_result_versions WHERE audit_batch_id=?", (batch_id,)).fetchone()["count"]
            conn.execute(
                "INSERT INTO audit_result_versions(audit_batch_id,version_label,summary_json,results_json,ai_analysis,created_at) VALUES(?,?,?,?,?,?)",
                (batch_id, f"V{version_count + 1}", batch["summary_json"], batch["results_json"], batch["ai_analysis"], now_text()),
            )
    batch_dir = Path(settings.upload_dir) / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    project_path = batch_dir / "项目基础资料.xlsx"
    project_path.write_bytes(await project_file.read())
    with get_conn() as conn:
        conn.execute("DELETE FROM uploaded_files WHERE audit_batch_id=? AND file_type='project_base'", (batch_id,))
        conn.execute(
            "INSERT INTO uploaded_files(audit_batch_id,file_type,original_name,storage_path,created_at) VALUES(?,?,?,?,?)",
            (batch_id, "project_base", project_file.filename, str(project_path), now_text()),
        )
        conn.execute(
            "UPDATE audit_batches SET status=?, progress=?, message=?, results_json=NULL, summary_json=NULL, ai_analysis=NULL WHERE id=?",
            ("待重新审核", 35, "项目已重新提交排班，待集团重新审核", batch_id),
        )
        upsert_project_status(conn, batch["project_name"], batch["project_code"], schedule_status="已重新提交", audit_status="待重新审核", rectification_status="已整改", upload_time=now_text())
    return {"batch_id": batch_id, "status": "待重新审核", "message": "排班已重新提交，无需重新上传合同和BI"}

@router.post("/audit-batches/{batch_id}/upload-project-base")
async def upload_project_base_only(batch_id: int, project_file: UploadFile = File(...)):
    if not project_file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="项目基础资料仅支持 .xlsx 文件")
    with get_conn() as conn:
        batch = conn.execute("SELECT * FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        if int(batch["is_locked"] or 0):
            raise HTTPException(status_code=400, detail="最终版已确认锁定，不能重新上传")
    batch_dir = Path(settings.upload_dir) / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    project_path = batch_dir / "项目基础资料.xlsx"
    project_path.write_bytes(await project_file.read())
    with get_conn() as conn:
        conn.execute("DELETE FROM uploaded_files WHERE audit_batch_id=? AND file_type='project_base'", (batch_id,))
        conn.execute(
            "INSERT INTO uploaded_files(audit_batch_id,file_type,original_name,storage_path,created_at) VALUES(?,?,?,?,?)",
            (batch_id, "project_base", project_file.filename, str(project_path), now_text()),
        )
        conn.execute(
            "UPDATE audit_batches SET status=?, progress=?, message=? WHERE id=?",
            ("待审核", 20, "项目基础资料已上传，审核时将自动读取BI_Data目录", batch_id),
        )
        upsert_project_status(conn, batch["project_name"], batch["project_code"], schedule_status="已上传", audit_status="待审核", upload_time=now_text())
    return {"batch_id": batch_id, "status": "待审核", "message": "项目基础资料已上传，审核时自动读取BI_Data目录"}

@router.post("/audit-batches/{batch_id}/validate")
def validate_files(batch_id: int):
    project_path, _ = _get_uploaded_paths(batch_id, require_attendance=False)
    result = validate_project_workbook(project_path)
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_batches SET status=?, progress=?, message=? WHERE id=?",
            ("待审核" if result["valid"] else "校验失败", 35, result["message"], batch_id),
        )
    return result

def _run_audit_task(batch_id: int, project_path: str, attendance_path: str | None, selected_project: dict):
    """后台审核任务，在单独线程中执行。"""
    try:
        results = run_audit(batch_id, project_path, attendance_path, selected_project)
        with get_conn() as conn:
            ensure_version_table(conn)
            history_count = conn.execute("SELECT COUNT(*) AS count FROM audit_result_versions WHERE audit_batch_id=?", (batch_id,)).fetchone()["count"]
            current_version = f"V{history_count + 1}"
            results["audit_version"] = current_version
            conn.execute(
                """
                UPDATE audit_batches
                SET status=?, progress=?, finished_at=?, message=?, project_name=?, project_code=?, supplier=?,
                    contract_no=?, audit_month=?, template_version=?, summary_json=?, results_json=?, ai_analysis=?
                WHERE id=?
                """,
                (
                    "审核完成",
                    100,
                    now_text(),
                    f"审核完成（{current_version}）",
                    results["project_info"].get("项目名称", ""),
                    results["project_info"].get("项目编码", ""),
                    results["project_info"].get("供应商", ""),
                    results["project_info"].get("合同编号", ""),
                    results["project_info"].get("审核月份", ""),
                    results["project_info"].get("模板版本", ""),
                    json_dumps(results["summary"]),
                    json_dumps(results),
                    results["ai_analysis"],
                    batch_id,
                ),
            )
            upsert_project_status(conn, results["project_info"].get("项目名称", ""), results["project_info"].get("项目编码", ""), audit_status="审核完成", rectification_status="待确认", upload_time=now_text())
    except ValueError as exc:
        message = str(exc)
        with get_conn() as conn:
            conn.execute(
                "UPDATE audit_batches SET status=?, progress=?, finished_at=?, message=? WHERE id=?",
                ("审核失败", 45, now_text(), message, batch_id),
            )
    except Exception as exc:
        message = f"审核执行失败：{exc}"
        with get_conn() as conn:
            conn.execute(
                "UPDATE audit_batches SET status=?, progress=?, finished_at=?, message=? WHERE id=?",
                ("审核失败", 45, now_text(), message, batch_id),
            )
    finally:
        _auditing_batches.discard(batch_id)

@router.post("/audit-batches/{batch_id}/start")
async def start_audit(batch_id: int, background_tasks: BackgroundTasks):
    # 防止同一批次重复审核
    if batch_id in _auditing_batches:
        raise HTTPException(status_code=409, detail="该批次正在审核中，请等待完成")
    with get_conn() as conn:
        ensure_version_table(conn)
        _ensure_batch_columns(conn)
        batch = conn.execute("SELECT project_name,project_code,audit_month,business_type,summary_json,results_json,ai_analysis,is_locked FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if batch and int(batch["is_locked"] or 0):
            raise HTTPException(status_code=400, detail="最终版已确认锁定，不能重新审核")
        if batch and batch["results_json"]:
            version_count = conn.execute("SELECT COUNT(*) AS count FROM audit_result_versions WHERE audit_batch_id=?", (batch_id,)).fetchone()["count"]
            conn.execute(
                "INSERT INTO audit_result_versions(audit_batch_id,version_label,summary_json,results_json,ai_analysis,created_at) VALUES(?,?,?,?,?,?)",
                (batch_id, f"V{version_count + 1}", batch["summary_json"], batch["results_json"], batch["ai_analysis"], now_text()),
            )
    project_path, attendance_path = _get_uploaded_paths(batch_id, batch=batch, require_attendance=True)
    selected_project = {
        "项目名称": batch["project_name"] if batch else "",
        "项目编码": batch["project_code"] if batch else "",
        "审核月份": batch["audit_month"] if batch else "",
        "审核业态": batch["business_type"] if batch and "business_type" in batch.keys() else "",
    }
    with get_conn() as conn:
        conn.execute(
            "UPDATE audit_batches SET status=?, progress=?, started_at=?, message=? WHERE id=?",
            ("审核中", 45, now_text(), "审核执行中", batch_id),
        )
    # 标记为审核中
    _auditing_batches.add(batch_id)
    # 提交后台任务，立即返回
    background_tasks.add_task(_run_audit_task, batch_id, project_path, attendance_path, selected_project)
    return {"batch_id": batch_id, "status": "审核中", "message": "审核已提交，正在后台执行，请轮询进度"}

@router.post("/audit-batches/{batch_id}/confirm-final")
def confirm_final(batch_id: int, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    with get_conn() as conn:
        batch = conn.execute("SELECT * FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        if not batch["results_json"]:
            raise HTTPException(status_code=400, detail="请先完成审核再确认最终版")
        if normalize_role(x_user_role) == "项目账号" and x_project_name and batch["project_name"] != decode_header_value(x_project_name):
            raise HTTPException(status_code=403, detail="项目账号不能确认其他项目的最终版")
        now = now_text()
        conn.execute(
            "UPDATE audit_batches SET status=?, is_locked=1, confirmed_at=?, confirmed_by=?, message=? WHERE id=?",
            ("已确认", now, x_user_role, "最终版已确认并锁定", batch_id),
        )
        upsert_project_status(conn, batch["project_name"], batch["project_code"], audit_status="已确认", rectification_status="最终版", upload_time=batch["finished_at"] or now)
    return {"batch_id": batch_id, "status": "已确认", "message": "最终版已确认并锁定"}

@router.get("/audit-batches/{batch_id}/versions")
def list_versions(batch_id: int):
    with get_conn() as conn:
        ensure_version_table(conn)
        rows = conn.execute("SELECT id,audit_batch_id,version_label,created_at FROM audit_result_versions WHERE audit_batch_id=? ORDER BY id", (batch_id,)).fetchall()
        batch = conn.execute("SELECT current_version,finished_at,is_locked,confirmed_at FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
    data = [dict(row) for row in rows]
    if batch and batch["current_version"]:
        data.append({"id": None, "audit_batch_id": batch_id, "version_label": batch["current_version"], "created_at": batch["finished_at"], "is_current": True, "is_locked": bool(batch["is_locked"])})
    return data

@router.get("/audit-batches/{batch_id}/progress")
def get_progress(batch_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT id,status,progress,message FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        return dict(row)

@router.get("/audit-batches/{batch_id}")
def get_batch(batch_id: int, x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="审核批次不存在")
        if normalize_role(x_user_role) == "项目账号" and x_project_name and row["project_name"] != decode_header_value(x_project_name):
            raise HTTPException(status_code=403, detail="项目账号不能查看其他项目数据")
        data = dict(row)
        data["summary"] = json_loads(data.pop("summary_json"), {})
        data["results"] = json_loads(data.pop("results_json"), {})
        return data

@router.get("/audit-batches")
def list_batches(x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    with get_conn() as conn:
        if normalize_role(x_user_role) == "项目账号" and x_project_name:
            rows = conn.execute("SELECT id,project_name,project_code,supplier,audit_month,status,progress,message,created_at,finished_at,summary_json FROM audit_batches WHERE project_name=? ORDER BY id DESC", (decode_header_value(x_project_name),)).fetchall()
        else:
            rows = conn.execute("SELECT id,project_name,project_code,supplier,audit_month,status,progress,message,created_at,finished_at,summary_json FROM audit_batches ORDER BY id DESC").fetchall()
        data = []
        for row in rows:
            item = dict(row)
            item["status"] = normalize_audit_status(item.get("status", ""))
            item["summary"] = json_loads(item.pop("summary_json"), {})
            data.append(item)
        return data

def _get_uploaded_paths(batch_id: int, batch=None, require_attendance: bool = True):
    with get_conn() as conn:
        if batch is None:
            batch = conn.execute("SELECT project_name,project_code,audit_month FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        rows = conn.execute("SELECT file_type,storage_path FROM uploaded_files WHERE audit_batch_id=?", (batch_id,)).fetchall()
    project_paths = [row["storage_path"] for row in rows if row["file_type"] == "project_base"]
    attendance_paths = [row["storage_path"] for row in rows if row["file_type"] == "bi_attendance"]
    if not attendance_paths and batch:
        attendance_paths = find_bi_data_files(batch["project_name"], batch["audit_month"])
    if not project_paths:
        raise HTTPException(status_code=400, detail="请先上传项目基础资料")
    if require_attendance and not attendance_paths:
        raise HTTPException(status_code=400, detail="当前月份BI未同步")
    if not attendance_paths:
        return project_paths[0], None
    # 只取第一个（最新的）BI文件，因为BI导出可能是"全部项目"的一个大文件
    return project_paths[0], attendance_paths[0]

def _normalize_month(text: str) -> str:
    """将月份字符串标准化为 YYYYMM 格式，用于匹配。"""
    import re
    text = str(text or "")
    match = re.search(r"(20\d{2})[-年._]?(\d{1,2})", text)
    if match:
        return f"{int(match.group(1)):04d}{int(match.group(2)):02d}"
    return text.replace("-", "").replace("年", "").replace("月", "")


def find_bi_data_files(project_name: str, audit_month: str) -> list[str]:
    """
    查找BI考勤数据文件。
    按月份筛选文件名，同时回退查找上一个月的文件（BI导出通常是上月数据）。
    项目匹配在解析BI数据时通过BI路径解析完成。
    """
    month_key = _normalize_month(audit_month or "")

    # 计算上一个月标准化键
    prev_month_key = ""
    if audit_month and "-" in str(audit_month):
        parts = str(audit_month).split("-")
        y, m = int(parts[0]), int(parts[1])
        prev_m = m - 1 if m > 1 else 12
        prev_y = y if m > 1 else y - 1
        prev_month_key = _normalize_month(f"{prev_y}-{prev_m:02d}")

    candidates = []
    for path in settings.bi_data_dir.glob("**/*"):
        if path.suffix.lower() not in {".xlsx", ".csv"}:
            continue
        name_key = _normalize_month(path.name)
        if month_key and month_key == name_key:
            candidates.append(str(path))
        elif prev_month_key and prev_month_key == name_key:
            candidates.append(str(path))
    return candidates

def upsert_project_status(conn, project_name: str, project_code: str = "", contract_status: str | None = None, schedule_status: str | None = None, audit_status: str | None = None, rectification_status: str | None = None, upload_time: str | None = None):
    if not project_name:
        return
    now = now_text()
    # Update ALL rows matching project_name + project_code (regardless of business_type)
    updates = {
        "contract_status": contract_status,
        "schedule_status": schedule_status,
        "audit_status": audit_status,
        "rectification_status": rectification_status,
        "upload_time": upload_time,
    }
    set_parts = ["updated_at=?"]
    values = [now]
    for key, value in updates.items():
        if value is not None:
            set_parts.append(f"{key}=?")
            values.append(value)
    values.extend([project_name, project_code or ""])
    # Update all matching rows
    conn.execute(
        f"UPDATE project_statuses SET {','.join(set_parts)} WHERE project_name=? AND IFNULL(project_code,'')=IFNULL(?, '')",
        values,
    )
    # Check if any rows were updated
    row = conn.execute(
        "SELECT id FROM project_statuses WHERE project_name=? AND IFNULL(project_code,'')=IFNULL(?, '') LIMIT 1",
        (project_name, project_code or ""),
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO project_statuses(project_name,project_code,contract_status,schedule_status,audit_status,rectification_status,upload_time,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (project_name, project_code or "", contract_status or "待上传", schedule_status or "待上传", audit_status or "待上传", rectification_status or "未整改", upload_time, now),
        )

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
