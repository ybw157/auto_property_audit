"""统一返回结构。

全平台接口统一用 Result 包裹业务数据，前端按 code/message/data 解析：
- code=0   成功
- code!=0  业务失败（前端按 message 提示，不抛 5xx）
这样 service 层只关心业务，HTTP 层只关心 401/403 等鉴权异常。
"""
from __future__ import annotations

from typing import Any


class Result:
    """统一返回对象。"""

    def __init__(self, code: int = 0, message: str = "ok", data: Any = None):
        self.code = code
        self.message = message
        self.data = data

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "data": self.data}

    @classmethod
    def ok(cls, data: Any = None, message: str = "ok") -> "Result":
        return cls(0, message, data)

    @classmethod
    def fail(cls, message: str = "error", code: int = 1, data: Any = None) -> "Result":
        return cls(code, message, data)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Result(code={self.code}, message={self.message!r}, data={self.data!r})"
