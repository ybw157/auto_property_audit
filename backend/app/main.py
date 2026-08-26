from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pathlib import Path

from app.api.v1 import audit_batches, results, reports, configs, logs, dashboard, templates, contracts, management, projects, auth
from app.core.database import init_db
from app.core.config import settings

app = FastAPI(title="物业集团保安保洁智能审核平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 登录鉴权中间件 ----------
# 放行路径：健康检查、静态文件、登录接口
_PUBLIC_PREFIXES = ("/auth/login",)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    # 非业务接口、静态文件、健康检查直接放行
    if not path.startswith("/api/v1") or path == "/api/v1/auth/login":
        return await call_next(request)
    user = auth.user_from_token(request)
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
Path(settings.bi_data_dir).mkdir(parents=True, exist_ok=True)

init_db()

app.mount("/files", StaticFiles(directory=settings.storage_dir), name="files")

app.include_router(audit_batches.router, prefix="/api/v1", tags=["审核批次"])
app.include_router(results.router, prefix="/api/v1", tags=["审核结果"])
app.include_router(reports.router, prefix="/api/v1", tags=["报告"])
app.include_router(configs.router, prefix="/api/v1", tags=["系统配置"])
app.include_router(logs.router, prefix="/api/v1", tags=["系统日志"])
app.include_router(dashboard.router, prefix="/api/v1", tags=["首页"])
app.include_router(templates.router, prefix="/api/v1", tags=["模板"])
app.include_router(contracts.router, prefix="/api/v1", tags=["合同规则库"])
app.include_router(management.router, prefix="/api/v1", tags=["集团管理"])
app.include_router(projects.router, prefix="/api/v1", tags=["项目主档"])
app.include_router(auth.router, prefix="/api/v1", tags=["认证"])

@app.get("/")
def health_check():
    return {"name": "物业集团保安保洁智能审核平台", "status": "running"}
