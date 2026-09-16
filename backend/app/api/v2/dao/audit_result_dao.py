"""审核结果数据库访问层。"""
from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db, now_text
from app.api.v2.models.audit_result_models import AuditResult


def save_audit_result(result: AuditResult) -> int:
    """保存审核结果（UPSERT）。

    定位键必须包含 service_type：同一 (项目, 业态, 月份) 下保安与保洁各存一条，
    否则后审核的服务类型会覆盖先审核的记录。
    """
    db: Session = next(get_db())
    try:
        existing = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_name == result.project_name,
                AuditResult.business_type == result.business_type,
                AuditResult.audit_month == result.audit_month,
                AuditResult.service_type == (result.service_type or ""),
            )
            .first()
        )
        if existing:
            existing.status = result.status
            existing.version = result.version
            existing.results_json = result.results_json
            existing.summary_json = result.summary_json
            existing.ai_analysis = result.ai_analysis
            existing.versions_json = result.versions_json
            existing.logs_json = result.logs_json
            existing.locked = result.locked
            existing.confirmed_by = result.confirmed_by
            existing.confirmed_at = result.confirmed_at
            existing.service_type = result.service_type
            existing.updated_at = now_text()
            db.commit()
            return existing.id
        else:
            db.add(result)
            db.commit()
            db.refresh(result)
            return result.id
    finally:
        db.close()


def get_audit_result(
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str = "",
) -> AuditResult | None:
    db: Session = next(get_db())
    try:
        q = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_name == project_name,
                AuditResult.business_type == business_type,
                AuditResult.audit_month == audit_month,
            )
        )
        if service_type:
            q = q.filter(AuditResult.service_type == service_type)
        return q.first()
    finally:
        db.close()


def list_audit_results(
    project_name: str = "",
    audit_month: str = "",
    business_type: str = "",
    service_type: str = "",
) -> list[AuditResult]:
    db: Session = next(get_db())
    try:
        q = db.query(AuditResult)
        if project_name:
            q = q.filter(AuditResult.project_name == project_name)
        if audit_month:
            q = q.filter(AuditResult.audit_month == audit_month)
        if business_type:
            q = q.filter(AuditResult.business_type == business_type)
        if service_type:
            q = q.filter(AuditResult.service_type == service_type)
        return q.order_by(
            AuditResult.project_name,
            AuditResult.business_type,
            AuditResult.audit_month,
        ).all()
    finally:
        db.close()


def _apply_scope(q, service_type: str = ""):
    """按 service_type 收窄查询范围。

    service_type 为空时不限定（兼容历史数据与未传该参数的调用方）。
    """
    if service_type:
        q = q.filter(AuditResult.service_type == service_type)
    return q


def update_audit_result_status(
    project_name: str,
    business_type: str,
    audit_month: str,
    status: str,
    service_type: str = "",
    **kwargs,
) -> None:
    db: Session = next(get_db())
    try:
        values = {AuditResult.status: status, AuditResult.updated_at: now_text()}
        for key, value in kwargs.items():
            if value is not None and hasattr(AuditResult, key):
                values[getattr(AuditResult, key)] = value
        q = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_name == project_name,
                AuditResult.business_type == business_type,
                AuditResult.audit_month == audit_month,
            )
        )
        _apply_scope(q, service_type).update(values)
        db.commit()
    finally:
        db.close()


def lock_audit_result(
    project_name: str,
    business_type: str,
    audit_month: str,
    confirmed_by: str,
    service_type: str = "",
) -> None:
    db: Session = next(get_db())
    try:
        q = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_name == project_name,
                AuditResult.business_type == business_type,
                AuditResult.audit_month == audit_month,
            )
        )
        _apply_scope(q, service_type).update({
            AuditResult.locked: 1,
            AuditResult.confirmed_by: confirmed_by,
            AuditResult.confirmed_at: now_text(),
            AuditResult.updated_at: now_text(),
            AuditResult.status: "已确认",
        })
        db.commit()
    finally:
        db.close()


def update_audit_result_fields(
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str = "",
    **fields,
) -> bool:
    db: Session = next(get_db())
    try:
        update_data = {}
        for k, v in fields.items():
            if v is not None and hasattr(AuditResult, k):
                update_data[getattr(AuditResult, k)] = v
        update_data[AuditResult.updated_at] = now_text()
        q = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_name == project_name,
                AuditResult.business_type == business_type,
                AuditResult.audit_month == audit_month,
            )
        )
        _apply_scope(q, service_type).update(update_data)
        db.commit()
        return True
    finally:
        db.close()