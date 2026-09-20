import json
from datetime import datetime
from typing import Any, Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.v2.core.config import settings
from app.api.v2.models.base import Base

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _migrate_contract_is_deleted()
    _drop_contract_uk_original_name()
    _migrate_position_service_type()
    _migrate_audit_result_scope()
    _drop_legacy_audit_result_locked()
    _migrate_audit_result_project_name()
    _seed_users()


def _migrate_position_service_type() -> None:
    """给 position_infos 补 service_type，并把定位唯一键扩为 (项目, 业态, 月份, 服务类型)。

    缺少 service_type 时，同一 (项目, 业态, 月份) 只能存一份排班，后上传的保安会
    覆盖先上传的保洁；create_all 不会为已存在的表补建索引，故在此显式迁移。
    """
    insp = inspect(engine)
    if "position_infos" not in insp.get_table_names():
        return
    columns = {col["name"] for col in insp.get_columns("position_infos")}
    if "service_type" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE position_infos ADD COLUMN service_type VARCHAR(50) DEFAULT '' NOT NULL")
            )
    # 旧唯一键只有三列，需要换成含 service_type 的四列键
    three_col_uk = None
    for idx in insp.get_indexes("position_infos"):
        cols = idx.get("column_names") or []
        if idx.get("unique") and set(cols) == {"project_name", "business_type", "audit_month"}:
            three_col_uk = idx.get("name")
            break
    existing_uk_cols = [
        set(idx.get("column_names") or [])
        for idx in inspect(engine).get_indexes("position_infos")
        if idx.get("unique")
    ]
    want_cols = {"project_name", "business_type", "audit_month", "service_type"}
    if want_cols not in existing_uk_cols:
        with engine.begin() as conn:
            if three_col_uk:
                conn.execute(text(f"DROP INDEX `{three_col_uk}` ON `position_infos`"))
            conn.execute(
                text(
                    "ALTER TABLE position_infos ADD UNIQUE INDEX "
                    "uk_position_scope (project_name, business_type, audit_month, service_type)"
                )
            )


def _migrate_audit_result_scope() -> None:
    """给 audit_results 补 service_type，并把定位唯一键扩为 (项目, 业态, 月份, 服务类型)。

    与 position_infos 同理：唯一键少一列时，同一 (项目, 业态, 月份) 下后审核的
    服务类型会整行覆盖先审核的那份结果。存量库由 tools/migration.sql 手工执行过，
    这里做一次幂等收敛，保证「新建库」与「存量库」最终拿到同一把键。
    """
    insp = inspect(engine)
    if "audit_results" not in insp.get_table_names():
        return
    columns = {col["name"] for col in insp.get_columns("audit_results")}
    if "service_type" not in columns:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE audit_results ADD COLUMN service_type VARCHAR(50) DEFAULT '' NOT NULL")
            )
    legacy_uk = None
    for idx in inspect(engine).get_indexes("audit_results"):
        cols = idx.get("column_names") or []
        if idx.get("unique") and set(cols) == {"project_name", "business_type", "audit_month"}:
            legacy_uk = idx.get("name")
            break
    existing_uk_cols = [
        set(idx.get("column_names") or [])
        for idx in inspect(engine).get_indexes("audit_results")
        if idx.get("unique")
    ]
    want_cols = {"project_name", "business_type", "audit_month", "service_type"}
    if want_cols not in existing_uk_cols:
        with engine.begin() as conn:
            if legacy_uk:
                conn.execute(text(f"DROP INDEX `{legacy_uk}` ON `audit_results`"))
            conn.execute(
                text(
                    "ALTER TABLE audit_results ADD UNIQUE INDEX "
                    "uq_audit_result_scope (project_name, business_type, audit_month, service_type)"
                )
            )


def _drop_legacy_audit_result_locked() -> None:
    """删除 audit_results 的历史遗留列 locked。

    locked 已从模型彻底废弃（后端代码零引用），但存量库里它仍是 NOT NULL 且无默认值，
    会让不带该列的 INSERT 直接报 1364「Field 'locked' doesn't have a default value」，
    导致审核结果无法落库。这里做一次性幂等清理。
    """
    insp = inspect(engine)
    if "audit_results" not in insp.get_table_names():
        return
    columns = {col["name"] for col in insp.get_columns("audit_results")}
    if "locked" not in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_results DROP COLUMN locked"))


def _migrate_audit_result_project_name() -> None:
    """把历史被「去项目二字」污染的 audit_results 项目名对齐回 position_infos。

    旧版 start_audit 落库前会把 project_name 里的「项目」二字去掉
    （如"长春金鹰世界项目" → "长春金鹰世界"），但查询/比对用的仍是原值，
    导致同一项目在 audit_results 与 position_infos 里落到两把键、版本号永不递增。
    本迁移把 audit_results 中"缺项目二字"的那批行补回，使其与编制表项目名一致。
    幂等：已一致或本就匹配的行不会被改动。
    """
    insp = inspect(engine)
    if "audit_results" not in insp.get_table_names() or "position_infos" not in insp.get_table_names():
        return
    with engine.connect() as conn:
        ar_names = [r[0] for r in conn.execute(text("SELECT DISTINCT project_name FROM audit_results")).all()]
        pos_names = {r[0] for r in conn.execute(text("SELECT DISTINCT project_name FROM position_infos")).all()}
    remap: dict[str, str] = {}
    for name in ar_names:
        if not name:
            continue
        candidate = name + "项目"
        # 优先对齐到带「项目」后缀的规范名（登录账号绑定的项目名）。
        # 旧逻辑把落库名 stripped 后，audit_results 里是「长春金鹰世界」而
        # 上传编制表用的是登录账号的「长春金鹰世界项目」；只要规范名存在于
        # 编制表，就把它补回，使审核结果行与编制表行落到同一把键、版本号能正常递增。
        if candidate in pos_names and candidate != name:
            remap[name] = candidate
    if not remap:
        return
    with engine.begin() as conn:
        for old, new in remap.items():
            # 避免与已存在的同范围行唯一键冲突（理论上旧逻辑不会产出同名满键行）
            exists = conn.execute(
                text(
                    "SELECT 1 FROM audit_results ar "
                    "WHERE ar.project_name = :new AND EXISTS ("
                    "SELECT 1 FROM audit_results x "
                    "WHERE x.project_name = :old "
                    "AND x.business_type = ar.business_type "
                    "AND x.audit_month = ar.audit_month "
                    "AND x.service_type = ar.service_type)"
                ),
                {"new": new, "old": old},
            ).first()
            if exists:
                print(f"[迁移跳过] audit_results 项目名 {old!r} → {new!r} 会与现存行唯一键冲突，已跳过")
                continue
            conn.execute(
                text("UPDATE audit_results SET project_name = :new WHERE project_name = :old"),
                {"new": new, "old": old},
            )
            print(f"[迁移] audit_results 项目名 {old!r} → {new!r}")


def _migrate_contract_is_deleted() -> None:
    insp = inspect(engine)
    if "contract" not in insp.get_table_names():
        return
    columns = {col["name"] for col in insp.get_columns("contract")}
    if "is_deleted" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE contract ADD COLUMN is_deleted INTEGER DEFAULT 0 NOT NULL"))


def _drop_contract_uk_original_name() -> None:
    insp = inspect(engine)
    if "contract" not in insp.get_table_names():
        return
    for idx in insp.get_indexes("contract"):
        if idx.get("name") == "uk_original_name":
            with engine.begin() as conn:
                conn.execute(text("DROP INDEX `uk_original_name` ON `contract`"))
            break


def now_text() -> datetime:
    return datetime.now()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    return json.loads(value)




def _seed_users() -> None:
    from app.api.v2.core.security import hash_password
    from app.api.v2.models.user import User

    defaults: list[dict[str, Any]] = [
        {
            "username": "group_admin",
            "role": True,
            "display_name": "集团管理员",
            "project_name": "",
            "project_code": "",
            "password": "admin123",
        },
        {
            "username": "project_user",
            "role": False,
            "display_name": "项目账号（示例）",
            "project_name": "南京金鹰中心",
            "project_code": "",
            "password": "proj123",
        },
    ]

    db = SessionLocal()
    try:
        for item in defaults:
            existing = db.query(User).filter(User.username == item["username"]).first()
            if existing is None:
                db.add(
                    User(
                        username=item["username"],
                        role=item["role"],
                        display_name=item["display_name"],
                        project_name=item["project_name"],
                        project_code=item["project_code"],
                        password_hash=hash_password(item["password"]),
                        status="active",
                    )
                )
            elif not existing.password_hash:
                existing.password_hash = hash_password(item["password"])
        db.commit()
    finally:
        db.close()
