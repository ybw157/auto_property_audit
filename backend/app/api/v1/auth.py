"""认证路由：登录 / 获取当前用户 / 修改密码。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.core.database import get_conn, now_text
from app.core.security import create_token, decode_token, hash_password, verify_password

router = APIRouter()


class LoginIn(BaseModel):
    username: str
    password: str


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


def _user_row(conn, username: str):
    return conn.execute(
        "SELECT * FROM system_users WHERE username=? AND status='active'",
        (username,),
    ).fetchone()


def get_current_user(request: Request) -> dict:
    """从请求中解析当前登录用户（依赖项）。中间件已校验 token 并写入 request.state.user。"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


@router.post("/auth/login")
def login(body: LoginIn):
    """账号密码登录，校验成功后返回 token 与用户信息。"""
    with get_conn() as conn:
        row = _user_row(conn, body.username.strip())
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    user_info = {
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"] or row["username"],
        "project_name": row["project_name"] or "",
        "project_code": row["project_code"] or "",
    }
    token = create_token(user_info)
    return {"token": token, "user": user_info}


@router.get("/auth/me")
def me(current: dict = Depends(get_current_user)):
    """返回当前登录用户信息。"""
    return current


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, current: dict = Depends(get_current_user)):
    """修改当前用户密码。"""
    with get_conn() as conn:
        row = _user_row(conn, current["username"])
        if not row or not verify_password(body.old_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")
        if len(body.new_password) < 6:
            raise HTTPException(status_code=400, detail="新密码至少 6 位")
        conn.execute(
            "UPDATE system_users SET password_hash=?, updated_at=? WHERE username=?",
            (hash_password(body.new_password), now_text(), current["username"]),
        )
    return {"message": "密码修改成功"}


def user_from_token(request: Request) -> dict | None:
    """从 Authorization 头解析用户信息，供中间件调用。"""
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    return decode_token(token)
