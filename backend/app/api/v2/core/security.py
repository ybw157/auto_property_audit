"""安全工具：密码哈希 + Token 签发/校验（零第三方依赖，基于 Python 标准库）。"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

# 密钥：优先读环境变量，否则用默认值（生产环境务必通过环境变量覆盖）
SECRET_KEY = os.getenv("AUTH_SECRET_KEY", "property-audit-platform-secret-2026")
# Token 有效期（秒），默认 24 小时
TOKEN_TTL = int(os.getenv("AUTH_TOKEN_TTL", str(60 * 60 * 24)))

_ITER = 200_000  # pbkdf2 迭代次数


def hash_password(password: str) -> str:
    """对明文密码做哈希，返回格式：pbkdf2_sha256$迭代次数$盐$哈希（均为 hex）。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """校验明文密码是否与存储的哈希匹配。"""
    if not stored or not stored.startswith("pbkdf2_sha256$"):
        return False
    try:
        _, iter_str, salt, expected_hex = stored.split("$", 3)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iter_str)
        )
        return hmac.compare_digest(digest.hex(), expected_hex)
    except Exception:
        return False


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def create_token(payload: dict[str, Any]) -> str:
    """签发 HMAC-SHA256 签名的 token，格式：payload.signature。"""
    body = dict(payload)
    body["exp"] = int(time.time()) + TOKEN_TTL
    payload_b64 = _b64encode(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def decode_token(token: str | None) -> dict[str, Any] | None:
    """校验 token 签名与有效期，成功返回 payload，失败返回 None。"""
    if not token or "." not in token:
        return None
    payload_b64, sig = token.rsplit(".", 1)
    expected_sig = hmac.new(SECRET_KEY.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload
