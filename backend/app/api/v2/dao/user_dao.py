"""用户数据访问层。"""
from sqlalchemy.orm import Session

from app.api.v2.core.database import get_db, now_text
from app.api.v2.core.security import hash_password, verify_password
from app.api.v2.models.user import User


def get_by_username(username: str) -> User | None:
    db: Session = next(get_db())
    try:
        return db.query(User).filter(
            User.username == username,
            User.status == "active",
        ).first()
    finally:
        db.close()


def verify_user(username: str, password: str) -> User | None:
    user = get_by_username(username)
    if not user or not verify_password(password, user.password_hash):
        return None
    return user


def update_password(username: str, new_password: str) -> None:
    db: Session = next(get_db())
    try:
        db.query(User).filter(User.username == username).update({
            User.password_hash: hash_password(new_password),
            User.updated_at: now_text(),
        })
        db.commit()
    finally:
        db.close()


def get_by_id(user_id: int) -> User | None:
    db: Session = next(get_db())
    try:
        return db.query(User).filter(User.id == user_id).first()
    finally:
        db.close()


def list_users() -> list[User]:
    db: Session = next(get_db())
    try:
        return db.query(User).order_by(User.id).all()
    finally:
        db.close()


def save_user(user: User) -> int:
    db: Session = next(get_db())
    try:
        existing = db.query(User).filter(User.username == user.username).first()
        if existing:
            existing.role = user.role
            existing.project_name = user.project_name
            existing.project_code = user.project_code
            existing.status = user.status
            existing.display_name = user.display_name
            existing.password_hash = user.password_hash
            existing.updated_at = now_text()
            db.commit()
            return existing.id
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.id
    finally:
        db.close()