from datetime import datetime
from sqlalchemy import String, DateTime, Boolean, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True) #主键
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False) #用户名
    password_hash: Mapped[str] = mapped_column(String(255), default="") #密码哈希
    display_name: Mapped[str] = mapped_column(String(100), default="") #显示名称
    role: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False) #角色: False=普通用户, True=管理员
    project_name: Mapped[str] = mapped_column(String(255), default="") #审核员所属的项目
    project_code: Mapped[str] = mapped_column(String(100), default="") #审核员所属的项目码
    status: Mapped[str] = mapped_column(String(20), default="active") #用户状态
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now()) #创建时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now() #更新时间
    )