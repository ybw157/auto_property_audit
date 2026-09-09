"""合同文件记录业务逻辑。"""
import os
import uuid
import logging
import threading
from datetime import datetime
from pathlib import Path
from fastapi import UploadFile, HTTPException
from app.api.v2.core.config import settings
from app.api.v2.dao import contract_dao
from app.api.v2.models.contract_models import ContractRecord

logger = logging.getLogger(__name__)


def upload_contract(file: UploadFile, project_name: str = "", force_project_name: bool = False) -> dict:
    """上传合同文件。

    :param file: 上传的文件
    :param project_name: 登录账号绑定的项目名
    :param force_project_name: 为 True 时忽略文件解析出的项目名，一律使用 project_name
    """
    settings.contract_dir.mkdir(parents=True, exist_ok=True)

    original_name = file.filename or "contract"
    _, ext = os.path.splitext(original_name)
    ext = ext.lower()
    if ext not in (".pdf", ".docx", ".doc", ".txt"):
        raise HTTPException(status_code=400, detail="仅支持 PDF、Word、TXT 文件")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"contract_{timestamp}_{uuid.uuid4().hex[:8]}{ext}"
    storage_path = str(settings.contract_dir / safe_name)

    content = file.file.read()
    with open(storage_path, "wb") as f:
        f.write(content)

    if ext == ".pdf":
        return _parse_and_save(original_name, ext, storage_path, project_name, force_project_name)
    elif ext in (".doc", ".docx"):
        return _parse_word_and_save(original_name, ext, storage_path, project_name, force_project_name)

    return _save_or_update(original_name, ext, storage_path, project_name=_normalize_project_name(project_name), business_type="", supplier="", contract_no="", contract_name="", service_type="", version="", start_date="", end_date="", rules=[])


def _save_or_update(original_name: str, ext: str, storage_path: str, **fields) -> dict:
    existing = contract_dao.get_contract_by_original_name_all(original_name)
    if existing:
        if existing.is_deleted == 1:
            contract_dao.restore_contract(existing.id, **fields, file_format=ext.lstrip("."), storage_path=storage_path)
        else:
            contract_dao.update_contract_full(existing.id, **fields, file_format=ext.lstrip("."), storage_path=storage_path)
        updated = contract_dao.get_contract_by_id(existing.id)
        return updated.to_dict() if updated else {}
    else:
        record = ContractRecord(original_name=original_name, file_format=ext.lstrip("."), storage_path=storage_path, **fields)
        record_id = contract_dao.save_contract(record)
        record.id = record_id
        return record.to_dict()


def _resolve_project_name(parsed_project: str, fallback: str, force_project_name: bool) -> str:
    """决定最终入库的项目名。

    文件解析出的项目名经常不准确（例如从文件名里截出"以外的其他保"），
    而列表查询又是按登录账号的项目名精确过滤的，两者不一致就会导致
    合同存进去了却永远查不出来。因此非管理员上传时强制使用账号绑定的项目名。
    """
    parsed_project = _normalize_project_name(parsed_project or "")
    if force_project_name:
        return _normalize_project_name(fallback)
    return parsed_project or _normalize_project_name(fallback)


def _normalize_project_name(name: str) -> str:
    """仅去除首尾空白，保留'项目'后缀。"""
    return name.strip() if name else name


def _parse_and_save(original_name: str, ext: str, storage_path: str, project_name: str = "", force_project_name: bool = False) -> dict:
    from app.api.v2.service.pdf_parser import extract_contract_metadata

    try:
        parsed = extract_contract_metadata(Path(storage_path), original_name)
        rules = parsed.get("rules", {})
        has_late_early = "late_early_tiers" in rules or (
            "late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules
        )
        has_required = has_late_early and "missing_clock_deduction" in rules

        logger.info(f"合同 {original_name} 解析完成")
        return _save_or_update(
            original_name, ext, storage_path,
            project_name=_resolve_project_name(parsed.get("project_name"), project_name, force_project_name),
            business_type=parsed.get("business_type", ""),
            supplier=parsed.get("supplier", ""),
            contract_no=parsed.get("contract_no", ""),
            contract_name=parsed.get("contract_name") or original_name,
            service_type=parsed.get("service_type", ""),
            version=parsed.get("version", ""),
            start_date=parsed.get("start_date", ""),
            end_date=parsed.get("end_date", ""),
            rules=rules,
            extract_status="done" if has_required else "failed",
        )

    except Exception as e:
        logger.error(f"合同解析异常: {e}")
        return _save_or_update(
            original_name, ext, storage_path,
            project_name=_normalize_project_name(project_name), business_type="", supplier="", contract_no="",
            contract_name="", service_type="", version="", start_date="", end_date="",
            rules=[], extract_status="failed",
        )


def _parse_word_and_save(original_name: str, ext: str, storage_path: str, project_name: str = "", force_project_name: bool = False) -> dict:
    from app.api.v2.service.word_parser import parse_contract

    try:
        parsed = parse_contract(storage_path, original_name, ext)

        logger.info(f"Word 合同 {original_name} 解析完成")
        return _save_or_update(
            original_name, ext, storage_path,
            project_name=_resolve_project_name(parsed.get("project_name"), project_name, force_project_name),
            business_type=parsed.get("business_type", ""),
            supplier=parsed.get("supplier", ""),
            contract_no=parsed.get("contract_no", ""),
            contract_name=parsed.get("contract_name", original_name),
            service_type=parsed.get("service_type", ""),
            start_date=parsed.get("start_date", ""),
            end_date=parsed.get("end_date", ""),
            rules=parsed.get("rules", []),
            extract_status="done",
        )

    except Exception as e:
        logger.error(f"Word 合同解析异常: {e}")
        return _save_or_update(
            original_name, ext, storage_path,
            project_name=_normalize_project_name(project_name), business_type="", supplier="", contract_no="",
            contract_name="", service_type="", version="", start_date="", end_date="",
            rules=[], extract_status="failed",
        )


def _run_extraction(contract_id: int, storage_path: str):
    try:
        contract_dao.update_contract_extract(contract_id, "extracting")

        from app.api.v2.service.pdf_parser import extract_contract_metadata

        contract = contract_dao.get_contract_by_id(contract_id)
        if not contract:
            return

        parsed = extract_contract_metadata(Path(storage_path), contract.original_name)
        rules = parsed.get("rules", {})
        has_late_early = "late_early_tiers" in rules or (
            "late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules
        )
        has_required = has_late_early and "missing_clock_deduction" in rules
        status = "done" if has_required else "failed"

        contract_dao.update_contract_extract_metadata(
            contract_id, status, rules,
            project_name=parsed.get("project_name"),
            business_type=parsed.get("business_type"),
            supplier=parsed.get("supplier"),
            contract_no=parsed.get("contract_no"),
            contract_name=parsed.get("contract_name"),
            service_type=parsed.get("service_type"),
            version=parsed.get("version"),
            start_date=parsed.get("start_date"),
            end_date=parsed.get("end_date"),
        )
        logger.info(f"合同 {contract_id} 重新提取完成: status={status}")

    except Exception as e:
        logger.error(f"合同 {contract_id} 提取异常: {e}")
        contract_dao.update_contract_extract(contract_id, "failed")


def _run_word_extraction(contract_id: int, storage_path: str):
    try:
        contract_dao.update_contract_extract(contract_id, "extracting")

        from app.api.v2.service.word_parser import parse_contract

        contract = contract_dao.get_contract_by_id(contract_id)
        if not contract:
            return

        parsed = parse_contract(storage_path, contract.original_name, f".{contract.file_format}")

        rules = parsed.get("rules", {})
        contract_dao.update_contract_extract_metadata(
            contract_id, "done", rules,
            project_name=parsed.get("project_name", ""),
            business_type=parsed.get("business_type", ""),
            supplier=parsed.get("supplier", ""),
            contract_no=parsed.get("contract_no", ""),
            contract_name=parsed.get("contract_name", ""),
            service_type=parsed.get("service_type", ""),
            start_date=parsed.get("start_date", ""),
            end_date=parsed.get("end_date", ""),
        )
        logger.info(f"Word 合同 {contract_id} 重新提取完成")

    except Exception as e:
        logger.error(f"Word 合同 {contract_id} 提取异常: {e}")
        contract_dao.update_contract_extract(contract_id, "failed")


def list_contracts(project_name: str = "", business_type: str = "") -> list[dict]:
    contracts = contract_dao.get_contracts(project_name, business_type)
    return [c.to_dict() for c in contracts]


def get_contract(contract_id: int) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return contract.to_dict()


def update_rules(contract_id: int, rules: list) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    contract_dao.update_contract_rules(contract_id, rules)
    return {"message": "规则更新成功", "contract_id": contract_id}


def trigger_extract(contract_id: int) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    if contract.file_format not in ("pdf", "doc", "docx"):
        raise HTTPException(status_code=400, detail="仅 PDF、Word 文件支持智能提取")

    contract_dao.update_contract_extract(contract_id, "extracting")

    if contract.file_format == "pdf":
        threading.Thread(
            target=_run_extraction,
            args=(contract_id, contract.storage_path),
            daemon=True,
        ).start()
    else:
        threading.Thread(
            target=_run_word_extraction,
            args=(contract_id, contract.storage_path),
            daemon=True,
        ).start()

    return {"message": "提取任务已触发", "contract_id": contract_id, "extract_status": "extracting"}


def get_extract_status(contract_id: int) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    return {
        "contract_id": contract_id,
        "extract_status": contract.extract_status,
        "rules": contract.rules,
    }


def toggle_status(contract_id: int, is_active: bool) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    status = "active" if is_active else "inactive"
    contract_dao.update_contract_status(contract_id, status, 1 if is_active else 0)
    return {"message": "状态更新成功", "contract_id": contract_id, "status": status}


def delete_contract(contract_id: int) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")
    if contract.is_active == 1:
        raise HTTPException(status_code=400, detail="合同正在启用中，请先停用后再删除")
    contract_dao.delete_contract(contract_id)
    return {"message": "合同已删除", "contract_id": contract_id}


def update_contract(contract_id: int, **fields) -> dict:
    contract = contract_dao.get_contract_by_id(contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="合同不存在")

    # 当 rules 被更新时，自动检查规则完整性并同步 extract_status
    rules = fields.get("rules")
    if rules and isinstance(rules, dict):
        has_late_early = "late_early_tiers" in rules or (
            "late_deduction_per_minute" in rules and "early_leave_deduction_per_minute" in rules
        )
        has_required = has_late_early and "missing_clock_deduction" in rules
        if has_required:
            fields["extract_status"] = "done"

    contract_dao.update_contract_full(contract_id, **fields)
    updated = contract_dao.get_contract_by_id(contract_id)
    return updated.to_dict() if updated else {}