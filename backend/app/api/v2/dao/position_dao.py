"""岗位信息数据库访问层。"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db
from app.api.v2.core.validators import require_service_type
from app.api.v2.models.position_models import PositionInfo, Position


def _pos_key_q(q, project_name: str, business_type: str, audit_month: str, service_type: str):
    """岗位记录的定位键：(项目, 业态, 月份, 服务类型)。

    服务类型是定位键的第四列，必须原样参与匹配：少了它，同一 (项目, 业态, 月份)
    下的保安与保洁会落到同一条记录上互相覆盖。字段缺失时直接报
    「缺少「服务类型」字段数据」，不做分支判断、不回退到空值或其它服务类型。
    """
    return q.filter(
        PositionInfo.project_name == project_name,
        PositionInfo.business_type == business_type,
        PositionInfo.audit_month == audit_month,
        PositionInfo.service_type == require_service_type(service_type),
    )


def save_position_info(info: PositionInfo) -> int:
    positions_data = [p.to_dict() for p in info.positions]
    # 服务类型缺失即报错，绝不落库成空串行
    info.service_type = require_service_type(getattr(info, "service_type", ""))
    db: Session = next(get_db())
    try:
        existing = _pos_key_q(
            db.query(PositionInfo),
            info.project_name,
            info.business_type,
            info.audit_month,
            info.service_type,
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
    service_type: str,
) -> PositionInfo | None:
    """按定位键取岗位数据。

    service_type 为必填定位列：既不回退到其它 service_type，也不回退到空值历史记录。
    未找到精确匹配时返回 None，由调用方决定如何提示用户。
    """
    db: Session = next(get_db())
    try:
        info = _pos_key_q(
            db.query(PositionInfo), project_name, business_type, audit_month, service_type
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

    用途：当 get_position_info(project_name, business_type, audit_month, service_type) 返回空时，
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


def list_service_types_for_scope(
    project_name: str, business_type: str, audit_month: str
) -> list[str]:
    """查询某 (项目,业态,月份) 下已上传过哪些服务类型。

    用于：service_type 指定值查不到时，告知用户已有哪些服务类型的排班数据。
    """
    db: Session = next(get_db())
    try:
        rows = (
            db.query(PositionInfo.service_type)
            .filter(
                PositionInfo.project_name == project_name,
                PositionInfo.business_type == business_type,
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
    service_type: str,
    **fields,
) -> bool:
    """按四列定位键更新岗位记录；服务类型缺失即报错，不会波及同类下的另一服务类型。"""
    db: Session = next(get_db())
    try:
        update_data = {}
        for k, v in fields.items():
            if v is not None and hasattr(PositionInfo, k):
                update_data[getattr(PositionInfo, k)] = v
        update_data[PositionInfo.updated_at] = datetime.now()  # type: ignore[assignment]
        (
            _pos_key_q(
                db.query(PositionInfo), project_name, business_type, audit_month, service_type
            ).update(update_data)
        )
        db.commit()
        return True
    finally:
        db.close()
