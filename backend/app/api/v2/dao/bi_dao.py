"""BI 考勤数据数据库访问层。"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db, now_text
from app.api.v2.models.attendance_models import BiAttendance


def save_bi_attendance(
    bi_month: str,
    employee_name: str,
    employee_id: str,
    project_name: str,
    position: str,
    attendance: dict,
) -> int:
    db: Session = next(get_db())
    try:
        existing = (
            db.query(BiAttendance)
            .filter(
                BiAttendance.bi_month == bi_month,
                BiAttendance.employee_name == employee_name,
                BiAttendance.employee_id == employee_id,
            )
            .first()
        )
        if existing:
            existing: BiAttendance
            existing.project_name = project_name
            existing.position = position
            existing.attendance_json = attendance
            existing.updated_at = now_text()
            db.commit()
            return existing.id
        else:
            record = BiAttendance(
                bi_month=bi_month,
                employee_name=employee_name,
                employee_id=employee_id,
                project_name=project_name,
                position=position,
                attendance_json=attendance,
            )
            db.add(record)
            db.commit()
            db.refresh(record)
            return record.id
    finally:
        db.close()


def save_bi_records(bi_month: str, records: list[dict]) -> int:
    count = 0
    for rec in records:
        save_bi_attendance(
            bi_month=bi_month,
            employee_name=rec.get("employee_name", ""),
            employee_id=rec.get("employee_id", ""),
            project_name=rec.get("project_name", ""),
            position=rec.get("position", ""),
            attendance=rec.get("attendance", {}),
        )
        count += 1
    return count


def get_bi_by_month(bi_month: str) -> list[dict]:
    db: Session = next(get_db())
    try:
        rows = (
            db.query(BiAttendance)
            .filter(BiAttendance.bi_month == bi_month)
            .all()
        )
        return [
            {
                "bi_month": row.bi_month,
                "employee_name": row.employee_name,
                "employee_id": row.employee_id,
                "project_name": row.project_name,
                "position": row.position,
                "attendance": row.attendance_json or {},
            }
            for row in rows
        ]
    finally:
        db.close()


def get_bi_upload_history() -> list[dict]:
    db: Session = next(get_db())
    try:
        rows = (
            db.query(
                BiAttendance.bi_month,
                BiAttendance.project_name,
                func.count(BiAttendance.id).label("record_count"),
                func.max(BiAttendance.updated_at).label("last_updated"),
            )
            .group_by(BiAttendance.bi_month, BiAttendance.project_name)
            .order_by(BiAttendance.bi_month.desc(), BiAttendance.project_name)
            .all()
        )
        return [
            {
                "bi_month": row.bi_month,
                "project_name": row.project_name,
                "record_count": row.record_count,
                "last_updated": row.last_updated.strftime("%Y-%m-%d %H:%M:%S") if row.last_updated else "",
            }
            for row in rows
        ]
    finally:
        db.close()


def get_bi_by_project(bi_month: str, project_name: str) -> list[dict]:
    db: Session = next(get_db())
    try:
        rows = (
            db.query(BiAttendance)
            .filter(
                BiAttendance.bi_month == bi_month,
                BiAttendance.project_name == project_name,
            )
            .all()
        )
        return [
            {
                "bi_month": row.bi_month,
                "employee_name": row.employee_name,
                "employee_id": row.employee_id,
                "project_name": row.project_name,
                "position": row.position,
                "attendance": row.attendance_json or {},
            }
            for row in rows
        ]
    finally:
        db.close()