"""用户控制器。"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.v2.dto.requests import LoginRequest, ChangePasswordRequest
from app.api.v2.service.user_service import login, get_me, change_password, list_users

router = APIRouter()


def get_current_user(request: Request) -> Any:
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user


@router.post("/user/login")
def login_endpoint(body: LoginRequest):
    return login(body.username, body.password)


@router.get("/user/me")
def me_endpoint(current: dict = Depends(get_current_user)):
    return current


@router.post("/user/change-password")
def change_password_endpoint(
    body: ChangePasswordRequest,
    current: dict = Depends(get_current_user),
):
    return change_password(current["username"], body.old_password, body.new_password)


@router.get("/user/users")
def list_users_endpoint():
    return list_users()