"""用户业务逻辑。"""
from fastapi import HTTPException

from app.api.v2.core.security import create_token, hash_password, verify_password
from app.api.v2.dao import user_dao


def login(username: str, password: str) -> dict:
    user = user_dao.verify_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    user_info = {
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name or user.username,
        "project_name": user.project_name or "",
        "project_code": user.project_code or "",
    }
    token = create_token(user_info)
    return {"token": token, "user": user_info}


def get_me(username: str) -> dict:
    user = user_dao.get_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user.to_dict()


def change_password(username: str, old_password: str, new_password: str) -> dict:
    user = user_dao.verify_user(username, old_password)
    if not user:
        raise HTTPException(status_code=400, detail="原密码错误")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    user_dao.update_password(username, new_password)
    return {"message": "密码修改成功"}


def list_users() -> list[dict]:
    users = user_dao.list_users()
    return [u.to_dict() for u in users]