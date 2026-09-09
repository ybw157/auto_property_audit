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
    _seed_users()


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
