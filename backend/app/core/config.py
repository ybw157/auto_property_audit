from pathlib import Path
from pydantic import BaseModel
import os

class Settings(BaseModel):
    app_name: str = "物业集团保安保洁智能审核平台"
    base_dir: Path = Path(__file__).resolve().parents[2]
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage")))
    upload_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "uploads"
    report_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "reports"
    template_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "templates"
    contract_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "contracts"
    bi_data_dir: Path = Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "BI_Data"
    database_path: Path = Path(os.getenv("DATABASE_PATH", str(Path(os.getenv("STORAGE_DIR", str(Path(__file__).resolve().parents[2] / "storage"))) / "audit_platform.db")))

settings = Settings()
