"""岗位信息数据库访问层。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db
from app.api.v2.models.position_models import PositionInfo, Position


def save_position_info(info: PositionInfo) -> int:
    positions_data = [p.to_dict() for p in info.positions]
    db: Session = next(get_db())
    try:
        existing = (
            db.query(PositionInfo)
            .filter(
                PositionInfo.project_name == info.project_name,
                PositionInfo.business_type == info.business_type,
                PositionInfo.audit_month == info.audit_month,
            )
            .first()
        )
        if existing:
            existing.supplier = info.supplier
            existing.positions_json = positions_data
            existing.contracted_count = info.contracted_count
            existing.actual_count = info.actual_count
            existing.updated_at = datetime.now()  # type: ignore[assignment]
            db.commit()
            return existing.id  # type: ignore[return-value]
        else:
            info.positions_json = positions_data
            db.add(info)
            db.commit()
            db.refresh(info)
            return info.id  # type: ignore[return-value]
    finally:
        db.close()


def get_position_info(
    project_name: str,
    business_type: str,
    audit_month: str,
) -> PositionInfo | None:
    db: Session = next(get_db())
    try:
        info = (
            db.query(PositionInfo)
            .filter(
                PositionInfo.project_name == project_name,
                PositionInfo.business_type == business_type,
                PositionInfo.audit_month == audit_month,
            )
            .first()
        )
        if info and info.positions_json:
            positions_data: list = info.positions_json  # type: ignore[assignment]
            info.positions = [
                Position.from_dict(p) for p in positions_data
            ]
        return info  # type: ignore[return-value]
    finally:
        db.close()


def get_all_position_info() -> list[PositionInfo]:
    db: Session = next(get_db())
    try:
        infos = db.query(PositionInfo).all()
        for info in infos:
            if info.positions_json:
                positions_data: list = info.positions_json  # type: ignore[assignment]
                info.positions = [
                    Position.from_dict(p) for p in positions_data
                ]
        return infos  # type: ignore[return-value]
    finally:
        db.close()


def update_position_info(
    project_name: str,
    business_type: str,
    audit_month: str,
    **fields,
) -> bool:
    db: Session = next(get_db())
    try:
        update_data = {}
        for k, v in fields.items():
            if v is not None and hasattr(PositionInfo, k):
                update_data[getattr(PositionInfo, k)] = v
        update_data[PositionInfo.updated_at] = datetime.now()  # type: ignore[assignment]
        (
            db.query(PositionInfo)
            .filter(
                PositionInfo.project_name == project_name,
                PositionInfo.business_type == business_type,
                PositionInfo.audit_month == audit_month,
            )
            .update(update_data)
        )
        db.commit()
        return True
    finally:
        db.close()
