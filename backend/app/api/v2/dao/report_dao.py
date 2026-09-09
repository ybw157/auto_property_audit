"""报告元数据 DAO —— 用 SQLite 跟踪已生成的 PDF 报告。"""
import sqlite3
from pathlib import Path

from app.api.v2.core.config import settings

_DB_PATH = Path(settings.storage_dir) / "reports" / "reports_meta.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS generated_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL,
            business_type TEXT NOT NULL,
            audit_month TEXT NOT NULL,
            report_type TEXT NOT NULL,
            file_format TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def save_report(
    project_name: str,
    business_type: str,
    audit_month: str,
    report_type: str,
    file_format: str,
    file_path: str,
    created_at: str,
) -> int:
    conn = _conn()
    try:
        conn.execute(
            "DELETE FROM generated_reports WHERE project_name=? AND business_type=? AND audit_month=? AND report_type=? AND file_format=?",
            (project_name, business_type, audit_month, report_type, file_format),
        )
        cur = conn.execute(
            "INSERT INTO generated_reports(project_name,business_type,audit_month,report_type,file_format,file_path,created_at) VALUES(?,?,?,?,?,?,?)",
            (project_name, business_type, audit_month, report_type, file_format, file_path, created_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_reports(
    project_name: str,
    business_type: str,
    audit_month: str,
) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM generated_reports WHERE project_name=? AND business_type=? AND audit_month=? ORDER BY id DESC",
            (project_name, business_type, audit_month),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_report(report_id: int) -> dict | None:
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT * FROM generated_reports WHERE id=?", (report_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
