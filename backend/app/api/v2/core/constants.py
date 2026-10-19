# -*- coding: utf-8 -*-
"""全局常量集中定义

约定：业务状态值统一用中文（数据库存储与导出报表同口径，业务人员直接可读），
代码中只允许引用本模块常量，禁止散落中文字符串字面量——写错会在 IDE/测试里立刻暴露。
"""
from __future__ import annotations


class AuditStatus:
    """审核结果状态（audit_results.status 列的合法取值）。

    生命周期：待审核 →（跑完审核）→ 已审核 →（异常确认提交/定稿）→ 已确认。
    """
    PENDING = "待审核"
    AUDITED = "已审核"
    CONFIRMED = "已确认"
