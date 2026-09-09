"""v2 API — Spring Boot + MVC 分层架构。

controller/  路由层（只负责路由定义和参数接收）
service/     业务逻辑层
dao/         数据访问层（封装 SQL 操作）
models/      dataclass 数据模型
dto/         Pydantic 请求/响应模型
core/        核心配置、数据库、安全、统一返回
utils/       工具函数（Excel、PDF、BI、规则引擎等）
"""