import os
from pathlib import Path
from pydantic import BaseModel


def _resolve_storage_dir() -> Path:
    base_dir = Path(__file__).resolve().parents[4]
    raw = Path(os.getenv("STORAGE_DIR", str(base_dir / "storage")))
    return raw if raw.is_absolute() else (base_dir / raw).resolve()


class Settings(BaseModel):
    app_name: str = "物业集团保安保洁智能审核平台"

    base_dir: Path = Path(__file__).resolve().parents[4]
    storage_dir: Path = _resolve_storage_dir()
    upload_dir: Path = storage_dir / "uploads"
    report_dir: Path = storage_dir / "reports"
    template_dir: Path = storage_dir / "templates"
    contract_dir: Path = storage_dir / "contracts"
    bi_dir: Path = storage_dir / "bi"

    mysql_host: str = os.getenv("MYSQL_HOST", "mysql")
    mysql_port: int = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user: str = os.getenv("MYSQL_USER", "root")
    mysql_password: str = os.getenv("MYSQL_PASSWORD", "123456")
    mysql_database: str = os.getenv("MYSQL_DATABASE", "property_audit")

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            "?charset=utf8mb4"
        )


settings = Settings()
