"""报告元数据 DAO —— 用 SQLite 跟踪已生成的 PDF 报告。"""
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.api.v2.core.config import settings

_DB_PATH = Path(settings.storage_dir) / "reports" / "reports_meta.db"

# 报告缓存保留天数：超过该天数的已生成报告会在保存新报告或应用启动时自动清理。
REPORT_RETENTION_DAYS = 21


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
        report_id = cur.lastrowid
    finally:
        conn.close()
    # 保存成功后清理超过保留期的旧报告，避免磁盘缓存无限堆积
    try:
        cleanup_expired_reports()
    except Exception as e:  # 清理失败不应影响本次保存结果
        print(f"[report_dao] 过期报告清理失败: {e}")
    return report_id


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


def _parse_dt(value: str) -> datetime | None:
    """解析 created_at 文本（如 '2026-09-09 07:55:34.623325'）。

    SQLite 中 created_at 由 str(datetime.now()) 写入。解析失败返回 None。
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def cleanup_expired_reports(max_age_days: int = REPORT_RETENTION_DAYS) -> int:
    """清理超过保留天数的报告缓存。

    同时删除 SQLite 索引记录与对应的 PDF 实体文件。
    返回实际清理的记录条数。
    """
    cutoff = datetime.now() - timedelta(days=max_age_days)

    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, file_path, created_at FROM generated_reports"
        ).fetchall()
    finally:
        conn.close()

    removed = 0
    for r in rows:
        created_at = _parse_dt(r["created_at"])
        if created_at is None or created_at >= cutoff:
            continue
        # 删除磁盘上的 PDF 实体文件（删除失败不应阻断后续清理）
        fp = Path(r["file_path"])
        try:
            if fp.exists():
                fp.unlink()
        except OSError as e:
            print(f"[report_dao] 删除过期报告文件失败 {fp}: {e}")
        conn2 = _conn()
        try:
            conn2.execute("DELETE FROM generated_reports WHERE id=?", (r["id"],))
            conn2.commit()
        finally:
            conn2.close()
        removed += 1
    return removed
