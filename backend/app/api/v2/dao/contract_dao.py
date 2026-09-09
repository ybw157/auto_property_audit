"""合同文件记录数据访问层。"""
from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db, now_text
from app.api.v2.models.contract_models import ContractRecord


def save_contract(contract: ContractRecord) -> int:
    db: Session = next(get_db())
    try:
        db.add(contract)
        db.commit()
        db.refresh(contract)
        return contract.id
    finally:
        db.close()


def get_contracts(project_name: str = "", business_type: str = "") -> list[ContractRecord]:
    db: Session = next(get_db())
    try:
        q = db.query(ContractRecord).filter(ContractRecord.is_deleted == 0)  # type: ignore[arg-type]
        if project_name:
            q = q.filter(ContractRecord.project_name == project_name)  # type: ignore[arg-type]
        if business_type:
            q = q.filter(ContractRecord.business_type == business_type)  # type: ignore[arg-type]
        return q.order_by(ContractRecord.id.desc()).all()  # type: ignore[return-value]
    finally:
        db.close()


def get_contract_by_id(contract_id: int) -> ContractRecord | None:
    db: Session = next(get_db())
    try:
        return db.query(ContractRecord).filter(
            ContractRecord.id == contract_id,
            ContractRecord.is_deleted == 0,
        ).first()  # type: ignore[return-value]
    finally:
        db.close()


def get_contract_by_original_name(original_name: str) -> ContractRecord | None:
    db: Session = next(get_db())
    try:
        return db.query(ContractRecord).filter(
            ContractRecord.original_name == original_name,
            ContractRecord.is_deleted == 0,
        ).first()  # type: ignore[return-value]
    finally:
        db.close()


def get_contract_by_original_name_all(original_name: str) -> ContractRecord | None:
    db: Session = next(get_db())
    try:
        return db.query(ContractRecord).filter(
            ContractRecord.original_name == original_name,
        ).first()  # type: ignore[return-value]
    finally:
        db.close()


def get_contract_by_name_and_bt(original_name: str, business_type: str, project_name: str | None = None) -> ContractRecord | None:
    """按 原始文件名 + 业态（项目账号再加项目名）定位合同。

    用于“解析入库”的去重：同名同业态视为同一份合同（覆盖更新），
    同名不同业态视为第二份合同（新建）。
    """
    db: Session = next(get_db())
    try:
        q = db.query(ContractRecord).filter(
            ContractRecord.original_name == original_name,
            ContractRecord.business_type == business_type,
            ContractRecord.is_deleted == 0,
        )
        if project_name:
            q = q.filter(ContractRecord.project_name == project_name)
        return q.order_by(ContractRecord.id.desc()).first()  # type: ignore[return-value]
    finally:
        db.close()


def restore_contract(contract_id: int, **fields) -> bool:
    db: Session = next(get_db())
    try:
        update_data = {getattr(ContractRecord, k): v for k, v in fields.items() if hasattr(ContractRecord, k)}
        update_data[ContractRecord.is_deleted] = 0
        update_data[ContractRecord.updated_at] = now_text()
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update(update_data)
        db.commit()
        return True
    finally:
        db.close()


def update_contract_full(contract_id: int, **fields) -> bool:
    db: Session = next(get_db())
    try:
        update_data = {getattr(ContractRecord, k): v for k, v in fields.items() if hasattr(ContractRecord, k)}
        update_data[ContractRecord.updated_at] = now_text()
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update(update_data)
        db.commit()
        return True
    finally:
        db.close()


def update_contract_rules(contract_id: int, rules: list) -> bool:
    db: Session = next(get_db())
    try:
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update({
            ContractRecord.rules: rules,
            ContractRecord.updated_at: now_text(),
        })
        db.commit()
        return True
    finally:
        db.close()


def update_contract_extract(contract_id: int, extract_status: str, rules: list | None = None) -> bool:
    db: Session = next(get_db())
    try:
        update_data: dict = {
            ContractRecord.extract_status: extract_status,
            ContractRecord.updated_at: now_text(),
        }
        if rules is not None:
            update_data[ContractRecord.rules] = rules
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update(update_data)
        db.commit()
        return True
    finally:
        db.close()


def update_contract_extract_metadata(
    contract_id: int,
    extract_status: str,
    rules: dict,
    project_name: str | None = None,
    business_type: str | None = None,
    supplier: str | None = None,
    contract_no: str | None = None,
    contract_name: str | None = None,
    service_type: str | None = None,
    version: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> bool:
    db: Session = next(get_db())
    try:
        update_data: dict = {
            ContractRecord.extract_status: extract_status,
            ContractRecord.rules: rules,
            ContractRecord.updated_at: now_text(),
        }
        if project_name is not None:
            update_data[ContractRecord.project_name] = project_name
        if business_type is not None:
            update_data[ContractRecord.business_type] = business_type
        if supplier is not None:
            update_data[ContractRecord.supplier] = supplier
        if contract_no is not None:
            update_data[ContractRecord.contract_no] = contract_no
        if contract_name is not None:
            update_data[ContractRecord.contract_name] = contract_name
        if service_type is not None:
            update_data[ContractRecord.service_type] = service_type
        if version is not None:
            update_data[ContractRecord.version] = version
        if start_date is not None:
            update_data[ContractRecord.start_date] = start_date
        if end_date is not None:
            update_data[ContractRecord.end_date] = end_date
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update(update_data)
        db.commit()
        return True
    finally:
        db.close()


def update_contract_status(contract_id: int, status: str, is_active: int = 1) -> bool:
    db: Session = next(get_db())
    try:
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update({
            ContractRecord.status: status,
            ContractRecord.is_active: is_active,
            ContractRecord.updated_at: now_text(),
        })
        db.commit()
        return True
    finally:
        db.close()


def delete_contract(contract_id: int) -> bool:
    db: Session = next(get_db())
    try:
        db.query(ContractRecord).filter(ContractRecord.id == contract_id).update({
            ContractRecord.is_deleted: 1,
            ContractRecord.updated_at: now_text(),
        })
        db.commit()
        return True
    finally:
        db.close()