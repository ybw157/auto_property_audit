from dotenv import load_dotenv

load_dotenv()

import uvicorn
from dataclasses import asdict, is_dataclass
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pathlib import Path

from app.api.v2.controller import (
    user_controller,
    position_controller,
    audit_result_controller,
    template_controller,
    contract_controller,
    bi_controller,
    report_controller,
)
from app.api.v2.core.database import init_db
from app.api.v2.core.config import settings
from app.api.v2.core.security import decode_token

def _dataclass_json_encoder(obj):
    """自定义 JSON 编码器，支持 dataclass 对象序列化。"""
    if is_dataclass(obj):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

app = FastAPI(
    title="物业集团保安保洁智能审核平台",
    version="2.0.1",

)

app.json_encoder = _dataclass_json_encoder

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 登录鉴权中间件 ----------
# 放行路径：健康检查、静态文件、登录接口


def user_from_token(request: Request) -> dict | None:
    """
    从请求头中获取用户信息

    :param request: 请求对象
    """

    auth = request.headers.get("authorization", "")

    if not auth.lower().startswith("bearer "):
        return None

    token = auth.split(" ", 1)[1].strip()

    return decode_token(token)

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # 非业务接口、静态文件、健康检查、登录接口直接放行
    if not path.startswith("/api/v2") or path == "/api/v2/user/login":
        return await call_next(request)
    user = user_from_token(request)
    if not user:
        return JSONResponse(status_code=401, content={"detail": "未登录或登录已过期，请重新登录"})
    # 将用户信息写入 request.state，供路由/依赖项使用
    request.state.user = user
    return await call_next(request)


Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
Path(settings.report_dir).mkdir(parents=True, exist_ok=True)
Path(settings.template_dir).mkdir(parents=True, exist_ok=True)
Path(settings.contract_dir).mkdir(parents=True, exist_ok=True)
Path(settings.bi_dir).mkdir(parents=True, exist_ok=True)

init_db()

# 启动即清理超过保留期（21 天）的过期报告，避免磁盘缓存无限堆积
from app.api.v2.dao import report_dao

report_dao.cleanup_expired_reports()


app.mount("/files", StaticFiles(directory=settings.storage_dir), name="files")

# 用户
app.include_router(user_controller.router,
                   prefix="/api/v2",
                   tags=["用户"])

# 岗位信息
app.include_router(position_controller.router,
                   prefix="/api/v2",
                   tags=["岗位信息"])

# 审核结果
app.include_router(audit_result_controller.router,
                   prefix="/api/v2",
                   tags=["审核结果"])

# 模板下载
app.include_router(template_controller.router,
                   prefix="/api/v2",
                   tags=["模板"])

# 合同文件
app.include_router(contract_controller.router,
                   prefix="/api/v2",
                   tags=["合同"])

# BI 考勤
app.include_router(bi_controller.router,
                   prefix="/api/v2",
                   tags=["BI考勤"])

# PDF 报告
app.include_router(report_controller.router,
                   prefix="/api/v2",
                   tags=["PDF报告"])


@app.get("/")
def health_check():
    return {"name": "物业集团保安保洁智能审核平台", "status": "running"}


if __name__ == "__main__":


    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
