"""登录身份与项目归属工具。

项目名统一在这里解析，避免各接口各自从请求参数取值导致越权或数据对不上：
管理员（role 为真）可以使用传入的项目名，空值表示不限制；
其余账号一律强制使用登录账号绑定的项目名，忽略任何传入值。
"""
from typing import Any

from fastapi import HTTPException, Request


def get_current_user(request: Request) -> dict:
    """从 request.state 中取登录用户信息。"""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="未登录或登录已过期，请重新登录")
    return user


def is_admin(user: dict) -> bool:
    """是否为集团管理员。"""
    return bool(user.get("role"))


def resolve_project_name(request: Request, requested: str = "") -> str:
    """解析本次请求实际可用的项目名。

    :param request: 当前请求
    :param requested: 调用方传入的项目名（前端传参或请求体字段）
    :return: 管理员返回 requested（空表示全部项目）；普通账号强制返回其绑定项目名
    """
    user = get_current_user(request)
    if is_admin(user):
        return (requested or "").strip()
    return (user.get("project_name") or "").strip()


def resolve_project_name_for(user: dict, requested: str = "") -> str:
    """已拿到 user 字典时解析项目名，逻辑同 resolve_project_name。"""
    if is_admin(user):
        return (requested or "").strip()
    return (user.get("project_name") or "").strip()


def get_user_any(request: Request) -> Any:
    """兼容旧签名，返回原始 user 对象。"""
    return get_current_user(request)
