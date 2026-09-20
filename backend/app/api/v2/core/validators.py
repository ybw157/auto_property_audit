"""必填字段校验。

统一在此定义「字段缺失即报错」的规则，供 DAO / Service / Controller 共用：

- 调用方原样传入字段值，本模块只做「非空」判断；
- 缺失时直接抛 400「缺少「xxx」字段数据」；
- **不做任何分支判断，不提供默认值，不回退到其它范围**。

「服务类型」是本项目定位键的第四列（项目 + 业态 + 月份 + 服务类型），
缺失时若继续往下走，保安与保洁会落到同一把键上互相覆盖，因此必须硬性拦截。
「项目名称」是定位键的第一列，且一律取自登录用户信息、不从上传文件解析，
缺失说明登录账号没有绑定项目，同样必须拦截，否则会写出无归属的岗位/审核数据。
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

# 服务类型 / 项目名称字段的展示名，报错文案统一取自这里
SERVICE_TYPE_LABEL = "服务类型"
PROJECT_NAME_LABEL = "项目名称"


def require_field(value: Any, field_label: str) -> str:
    """要求字段非空，返回去空白后的值；为空直接报错。"""
    text = str(value if value is not None else "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"缺少「{field_label}」字段数据")
    return text


def require_service_type(service_type: Any) -> str:
    """要求服务类型（保安 / 保洁）非空。

    服务类型属于定位键的组成部分，因此缺失时不区分场景、不尝试兼容，
    一律报「缺少「服务类型」字段数据」。
    """
    return require_field(service_type, SERVICE_TYPE_LABEL)


def require_project_name(project_name: Any) -> str:
    """要求项目名称非空。

    项目名称一律取自登录用户信息（controller 层 resolve_project_name），
    上传的 Excel 里即使有「项目名称」列也不再解析，因此这里拿到空值只可能是
    「登录账号未绑定项目」。此时直接报错，不做兜底、不回退到文件里的项目名。
    """
    return require_field(project_name, PROJECT_NAME_LABEL)
