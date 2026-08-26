import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from app.core.config import settings

PROJECT_MASTER = [
    ("南京金鹰中心", ["商业", "写字楼", "酒店"]),
    ("南京汉中新城", ["商业", "写字楼"]),
    ("南京珠江壹号", ["商业", "写字楼", "酒店"]),
    ("南京湖滨天地", ["商业", "街区"]),
    ("江宁金鹰天地", ["商业", "住宅", "酒店"]),
    ("南京金鹰世界", ["商业", "写字楼", "酒店"]),
    ("上海金鹰国际", ["商业"]),
    ("芜湖金鹰商城", ["商业", "写字楼", "酒店"]),
    ("芜湖金鹰国际", ["商业", "住宅", "写字楼"]),
    ("宿迁金鹰天地", ["商业", "街区"]),
    ("马鞍山金鹰天地", ["商业", "住宅", "写字楼", "街区"]),
    ("丹阳金鹰天地", ["商业", "写字楼", "街区"]),
    ("昆山金鹰天地", ["商业", "写字楼", "街区"]),
    ("泰州金鹰天地", ["商业", "住宅", "街区"]),
    ("昆明金鹰天地", ["商业", "酒店"]),
    ("苏州金鹰国际", ["商业"]),
    ("盐城金鹰国际", ["商业"]),
    ("盐城金鹰奥莱", ["商业", "街区"]),
    ("盐城金鹰天地", ["商业", "写字楼", "街区", "住宅"]),
    ("南通金鹰中心", ["商业"]),
    ("扬州新城市中心", ["商业"]),
    ("扬州文昌金鹰国际", ["商业"]),
    ("扬州京华金鹰国际", ["商业"]),
    ("徐州彭城金鹰国际", ["商业"]),
    ("徐州人民金鹰国际", ["商业"]),
    ("淮安金鹰国际", ["商业"]),
    ("西安金鹰国际", ["商业"]),
    ("淮北金鹰国际", ["商业"]),
    ("溧阳店", ["商业"]),
    ("南通人民路店", ["商业"]),
    ("昆山住宅", ["住宅"]),
    ("连云港住宅", ["住宅"]),
    ("南通金鹰世界", ["住宅"]),
    ("长春金鹰世界", ["住宅"]),
    ("南京金鹰花园", ["住宅"]),
    ("南通八仙城", ["住宅"]),
    ("上海金鹰华庭", ["住宅"]),
    ("宿迁金鹰花园", ["住宅"]),
    ("常州凯悦中心花园", ["住宅"]),
    ("江都文昌华府", ["住宅"]),
    ("芜湖金鹰购物中心", ["商业"]),
    ("芜湖金鹰国际商城", ["写字楼"]),
]

def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)

@contextmanager
def get_conn():
    conn = sqlite3.connect(settings.database_path, timeout=30)
    conn.row_factory = sqlite3.Row
    # 启用WAL模式，避免读写锁冲突
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    # 优化并发性能
    conn.execute("PRAGMA synchronous=NORMAL")  # WAL模式下NORMAL足够安全且更快
    conn.execute("PRAGMA cache_size=-8000")  # 8MB缓存
    conn.execute("PRAGMA temp_store=MEMORY")  # 临时表存内存
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init_db() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS audit_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT,
                project_code TEXT,
                supplier TEXT,
                contract_no TEXT,
                audit_month TEXT,
                template_version TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                progress INTEGER NOT NULL DEFAULT 0,
                message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                summary_json TEXT,
                results_json TEXT,
                ai_analysis TEXT
            );

            CREATE TABLE IF NOT EXISTS uploaded_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_batch_id INTEGER NOT NULL,
                file_type TEXT NOT NULL,
                original_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_batch_id INTEGER NOT NULL,
                scope_type TEXT NOT NULL,
                scope_name TEXT,
                step_name TEXT NOT NULL,
                rule_key TEXT,
                input_json TEXT,
                output_json TEXT,
                message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS generated_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_batch_id INTEGER NOT NULL,
                report_type TEXT NOT NULL,
                file_format TEXT NOT NULL,
                file_path TEXT NOT NULL,
                download_url TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_result_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                audit_batch_id INTEGER NOT NULL,
                version_label TEXT NOT NULL,
                summary_json TEXT,
                results_json TEXT,
                ai_analysis TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL,
                project_name TEXT,
                project_code TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_rule_center (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_code TEXT,
                service_type TEXT NOT NULL,
                contract_id INTEGER,
                rules_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '待确认',
                version_label TEXT NOT NULL DEFAULT 'V1',
                confirmed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_statuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_code TEXT,
                business_type TEXT,
                contract_status TEXT NOT NULL DEFAULT '待上传',
                schedule_status TEXT NOT NULL DEFAULT '待上传',
                audit_status TEXT NOT NULL DEFAULT '待上传',
                rectification_status TEXT NOT NULL DEFAULT '未整改',
                upload_time TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_business_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_code TEXT,
                business_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '启用',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(project_name,business_type)
            );

            CREATE TABLE IF NOT EXISTS bi_sync_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT,
                project_code TEXT,
                audit_month TEXT NOT NULL,
                business_type TEXT,
                file_name TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                sync_status TEXT NOT NULL DEFAULT '已同步',
                synced_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rule_configs (
                key TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                value TEXT NOT NULL,
                value_type TEXT NOT NULL,
                group_name TEXT NOT NULL,
                description TEXT
            );

            CREATE TABLE IF NOT EXISTS project_contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_code TEXT,
                business_type TEXT,
                supplier TEXT,
                contract_no TEXT,
                contract_name TEXT NOT NULL,
                service_type TEXT,
                version TEXT,
                start_date TEXT,
                end_date TEXT,
                original_name TEXT NOT NULL,
                file_format TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                rules_json TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_bi_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                project_code TEXT,
                service_type TEXT NOT NULL,
                business_type TEXT,
                bi_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        defaults = [
            ("late_grace_minutes", "迟到宽限分钟", "5", "number", "考勤参数", "超过班次上班时间多少分钟后判定迟到"),
            ("early_leave_grace_minutes", "早退宽限分钟", "5", "number", "考勤参数", "早于班次下班时间多少分钟判定早退"),
            ("minimum_work_hour_ratio", "最低工时比例", "0.9", "number", "考勤参数", "实际工时低于标准工时比例时判定工时不足"),
            ("contract_deduction_coefficient", "合同扣款系数", "1", "number", "扣款参数", "岗位缺编扣款系数，由合同提取覆盖"),
            ("missing_clock_deduction", "漏打卡扣款", "20", "number", "扣款参数", "漏打卡单次扣款，由合同提取覆盖"),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO rule_configs(key,label,value,value_type,group_name,description) VALUES(?,?,?,?,?,?)",
            defaults,
        )
        ensure_columns(conn)
        seed_system_users(conn)
        seed_project_master(conn)

def ensure_columns(conn) -> None:
    add_column_if_missing(conn, "audit_batches", "business_type", "TEXT")
    add_column_if_missing(conn, "audit_batches", "current_version", "TEXT")
    add_column_if_missing(conn, "audit_batches", "is_locked", "INTEGER NOT NULL DEFAULT 0")
    add_column_if_missing(conn, "audit_batches", "confirmed_at", "TEXT")
    add_column_if_missing(conn, "audit_batches", "confirmed_by", "TEXT")
    add_column_if_missing(conn, "uploaded_files", "version_label", "TEXT")
    add_column_if_missing(conn, "uploaded_files", "business_type", "TEXT")
    add_column_if_missing(conn, "project_statuses", "business_type", "TEXT")
    add_column_if_missing(conn, "project_contracts", "business_type", "TEXT")
    add_column_if_missing(conn, "project_rule_center", "business_type", "TEXT")
    # 登录认证：给用户表加密码哈希列与显示名列
    add_column_if_missing(conn, "system_users", "password_hash", "TEXT")
    add_column_if_missing(conn, "system_users", "display_name", "TEXT")

def add_column_if_missing(conn, table: str, column: str, definition: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def seed_system_users(conn) -> None:
    """初始化默认账号。新库直接写入密码；已有库若密码为空则补上默认密码。"""
    from app.core.security import hash_password

    now = now_text()
    defaults = [
        {
            "username": "group_admin",
            "role": "集团管理员",
            "display_name": "集团管理员",
            "project_name": "",
            "project_code": "",
            "password": "admin123",
        },
        {
            "username": "project_user",
            "role": "项目账号",
            "display_name": "项目账号（示例）",
            "project_name": "南京金鹰中心",
            "project_code": "",
            "password": "proj123",
        },
    ]
    for item in defaults:
        # 若用户不存在则创建
        row = conn.execute(
            "SELECT id, password_hash FROM system_users WHERE username=?",
            (item["username"],),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO system_users(username,role,display_name,project_name,project_code,password_hash,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    item["username"],
                    item["role"],
                    item["display_name"],
                    item["project_name"],
                    item["project_code"],
                    hash_password(item["password"]),
                    "active",
                    now,
                    now,
                ),
            )
        elif not row["password_hash"]:
            # 老用户首次升级：补默认密码
            conn.execute(
                "UPDATE system_users SET password_hash=?, updated_at=? WHERE id=?",
                (hash_password(item["password"]), now, row["id"]),
            )

def seed_project_master(conn) -> None:
    now = now_text()
    for project_name, business_types in PROJECT_MASTER:
        for business_type in business_types:
            conn.execute(
                """
                INSERT OR IGNORE INTO project_business_types(project_name,project_code,business_type,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                """,
                (project_name, "", business_type, "启用", now, now),
            )
