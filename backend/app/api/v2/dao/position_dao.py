"""岗位信息数据库访问层。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db
from app.api.v2.models.position_models import PositionInfo, Position


def _pos_key_q(q, project_name: str, business_type: str, audit_month: str, service_type: str = ""):
    """岗位记录的定位条件：(项目, 业态, 月份, 服务类型)。

    service_type 必须参与定位，否则同一业态+月份下后上传的保安会覆盖先上传的保洁。
    """
    return q.filter(
        PositionInfo.project_name == project_name,
        PositionInfo.business_type == business_type,
        PositionInfo.audit_month == audit_month,
        PositionInfo.service_type == service_type,
    )


def save_position_info(info: PositionInfo) -> int:
    positions_data = [p.to_dict() for p in info.positions]
    db: Session = next(get_db())
    try:
        existing = _pos_key_q(
            db.query(PositionInfo),
            info.project_name,
            info.business_type,
            info.audit_month,
            getattr(info, "service_type", "") or "",
        ).first()
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
    service_type: str = "",
) -> PositionInfo | None:
    """取岗位数据。

    service_type 非空时先取该服务类型自己的排班；查不到则回退到 service_type 为空的
    历史记录，兼容改造前上传的（不区分服务类型的）排班数据。
    """
    db: Session = next(get_db())
    try:
        info = _pos_key_q(
            db.query(PositionInfo), project_name, business_type, audit_month, service_type or ""
        ).first()
        if info is None and service_type:
            info = _pos_key_q(
                db.query(PositionInfo), project_name, business_type, audit_month, ""
            ).first()
        if info and info.positions_json:
            positions_data: list = info.positions_json  # type: ignore[assignment]
            info.positions = [
                Position.from_dict(p) for p in positions_data
            ]
        return info  # type: ignore[return-value]
    finally:
        db.close()


def list_uploaded_business_types(project_name: str, audit_month: str) -> list[str]:
    """查询某项目某月份**已上传**岗位数据的业态列表。

    用途：当 get_position_info(project_name, business_type, audit_month) 返回空时，
    借此区分两种失败原因——
      - 返回空列表 → 该项目当月确实还没上传岗位数据；
      - 返回非空   → 数据已上传，只是传入的 business_type 与已上传业态不匹配。
    """
    db: Session = next(get_db())
    try:
        rows = (
            db.query(PositionInfo.business_type)
            .filter(
                PositionInfo.project_name == project_name,
                PositionInfo.audit_month == audit_month,
            )
            .all()
        )
        return sorted({str(r[0]).strip() for r in rows if r[0]})
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
