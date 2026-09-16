# 物业集团保安保洁智能审核平台

集团级保安 / 保洁外包**履约审核**与**人员考勤扣款审核**平台。运行方式：浏览器访问前端（SPA），前端调用 FastAPI 后端，后端以确定性规则引擎读取 MySQL 中的岗位基础资料、BI 考勤、合同条款，计算岗位缺编扣款与人员考勤扣款，并生成 PDF 审核报告。

> 当前审核为**确定性规则引擎**，不依赖大模型即可完成全部计算。代码内已内置基于 LangGraph 的合同智能提取 Agent（`app/agent/`），但**未默认接入生产解析路径**，生产合同解析走正则 + Tesseract OCR。详情见文末「实现说明与已知事项」。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | React 19 + TypeScript + Vite 6 + Tailwind CSS 3 + react-router-dom 7 |
| 后端 | Python 3.11 + FastAPI 0.115 + Uvicorn |
| 数据库 | **MySQL 8.0**（SQLAlchemy 2 + PyMySQL 驱动） |
| 鉴权 | JWT（登录签发，中间件校验 `Authorization: Bearer`） |
| Excel | openpyxl |
| PDF | ReportLab 4 |
| 合同 OCR | pytesseract + Tesseract（扫描件 / 图片型 PDF 文字识别） |
| 可选 LLM | langchain / langgraph（合同智能提取 Agent，默认未启用） |

## 系统依赖（本地运行前需安装）

### 1. MySQL 8.0
后端通过 `mysql+pymysql` 连接。本地运行需自行准备 MySQL 实例并建库 `property_audit`（表结构由后端启动时 `init_db()` 自动创建）。Docker 部署由 `docker-compose.yml` 的 `mysql` 服务提供。

### 2. Tesseract OCR（仅影响 PDF 扫描件合同识别）
合同解析对扫描件 / 图片型 PDF 需要 Tesseract 识别文字。Python 包 `pytesseract` 已在 `requirements.txt` 中，但 Tesseract 二进制需单独安装。纯文本 PDF / Word 合同不依赖它。

- **Windows**：下载 https://github.com/UB-Mannheim/tesseract/wiki 安装包，安装时勾选 **Chinese simplified (chi_sim)**，默认路径 `C:\Program Files\Tesseract-OCR\`（代码会自动检测）。
- **Linux (Ubuntu/Debian)**：`sudo apt install tesseract-ocr tesseract-ocr-chi-sim`
- **macOS**：`brew install tesseract tesseract-lang`
- 验证：`tesseract --version`

### 3. Node.js 20+（前端）

---

## 目录结构

```
auto_property_audit/
├── docker-compose.yml          # 一键部署：mysql + backend + frontend(nginx)
├── backend/
│   ├── app/
│   │   ├── main.py             # FastAPI 入口：路由注册、鉴权中间件、静态挂载
│   │   ├── agent/              # LangGraph 合同提取 Agent（实验性，未默认启用）
│   │   └── api/v2/
│   │       ├── core/          # config（读环境变量）、database、security(JWT)
│   │       ├── models/        # SQLAlchemy 模型（contract/position/audit/bi/user 等）
│   │       ├── dao/           # 数据访问层
│   │       ├── dto/           # 请求/响应结构
│   │       ├── service/       # 业务逻辑（audit_*/contract_*/bi_*/position_*）
│   │       ├── controller/    # 路由（user/position/audit_result/template/contract/bi/report）
│   │       └── utils/         # 解析器（pdf_parser/word_parser/excel_*）、pdf_report 等
│   ├── storage/                # 运行时文件：uploads/reports/templates/contracts/bi
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    ├── src/
    │   ├── pages/             # Dashboard/ProjectManagement/AiAudit/ContractManagement/
    │   │                      #   AuditResults/ConfirmationPage/BiUpload/BiSync/
    │   │                      #   UserManagement/Login/PdfReports
    │   ├── components/        # Layout/DataTable/ReportDownloads/ServiceTypeTabs/...
    │   ├── hooks/             # useAuth/useAuditContext/useServiceTypes
    │   └── services/          # api.ts（请求封装）、configCache、contractDraftCache
    ├── vite.config.ts         # base: '/audit/'，dev 代理 /api → 127.0.0.1:8000
    ├── nginx.conf             # 生产：/audit/ 托管 SPA，/api、/files 反代后端
    └── Dockerfile
```

---

## 快速开始（本地开发）

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # Windows；Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 配置数据库连接（见下「配置」）。最简：本地 MySQL 在 localhost
MYSQL_HOST=localhost MYSQL_PORT=3306 MYSQL_USER=root MYSQL_PASSWORD=123456 MYSQL_DATABASE=property_audit \
  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

启动后：
- 健康检查：`GET /`（返回 `status: running`）
- 接口文档：Swagger `http://localhost:8000/docs`、OpenAPI `http://localhost:8000/openapi.json`
- 静态文件（上传的 Excel / 生成的 PDF）：`/files/...`

### 前端

```bash
cd frontend
npm install
npm run dev
```

- 开发服务器：`http://localhost:5173`，项目入口在子路径 **`http://localhost:5173/audit/`**（vite `base: '/audit/'`）。
- 前端 API 默认走同源 `/api/v2/...`，开发时由 vite 代理到 `127.0.0.1:8000`，**无需额外配置后端地址**。如需自定义，可设置环境变量 `VITE_API_BASE_URL`。

---

## 配置

后端配置全部通过**环境变量**读取（`app/api/v2/core/config.py`）。`app/main.py` 启动时调用 `load_dotenv()`，因此 `backend/.env` 也会被加载；Docker 部署则通过 `docker-compose.yml` 的 `environment` 注入。

| 变量 | 说明 | 默认值（无 .env / 无注入时） |
|---|---|---|
| `MYSQL_HOST` | MySQL 主机 | `mysql`（即 docker 服务名；本地非 docker 请改 `localhost`） |
| `MYSQL_PORT` | MySQL 端口 | `3306` |
| `MYSQL_USER` | 用户名 | `root` |
| `MYSQL_PASSWORD` | 密码 | `123456` |
| `MYSQL_DATABASE` | 数据库名 | `property_audit` |
| `STORAGE_DIR` | 运行时文件根目录 | `<backend>/storage` |

> 本地非 Docker 运行务必显式设置 `MYSQL_HOST=localhost`，否则会按默认连主机名 `mysql` 而失败。

---

## 典型业务流程

1. **上传岗位基础资料**：`POST /api/v2/positions/upload`（Excel，工作表按别名匹配，见下）。
2. **上传 BI 考勤**：`POST /api/v2/bi/upload?bi_month=YYYYMM`。
3. **维护合同与扣款细则**：`POST /api/v2/contracts/upload` 或 `contracts/parse` 上传 PDF/Word/TXT 合同 → 解析出扣款细则 → 在细则卡片中确认保存（`PUT /api/v2/contracts/{id}/rules`）。
4. **发起审核**：`POST /api/v2/audit-results/start`（参数：项目名、审核月份、业态、服务类型）。引擎读取库内岗位 / 考勤 / 合同，分别计算**岗位缺编扣款**与**人员考勤扣款**。
5. **异常确认与复核**：`POST .../confirm-exceptions` 处理待复核条目；`POST .../confirm` 确认；`POST .../finalize` 终审锁定（锁定后不可再改）。
6. **生成报告**：`POST /api/v2/reports/generate?report_type=attendance|summary` → `GET .../reports/{id}/download`（PDF）。

两类扣款**分开计算、分开展示、合并汇总**。审核为确定性规则，结果可追溯。

---

## 功能模块与 API 一览

所有业务接口前缀为 `/api/v2`，除登录、模板下载、静态资源外均需 `Authorization: Bearer <token>`。

| 模块 | 主要接口 |
|---|---|
| 用户 | `POST /user/login`、`GET /user/me`、`POST /user/change-password`、`GET /user/users` |
| 岗位基础资料 | `POST /positions/upload`、`GET /positions`、`PUT /positions/update` |
| 审核结果 | `GET /audit-results`、`GET /audit-results/detail`、`POST /audit-results/start`、`POST /audit-results/confirm`、`PUT /audit-results/update`、`PUT /audit-results/confirm-exceptions`、`POST /audit-results/finalize` |
| 模板 | `GET /templates/{template_type}`（`project_base`=项目基础资料模板，其他值=BI考勤模板） |
| 合同 | `POST /contracts/upload`、`POST /contracts/parse`、`POST /contracts`、`GET /contracts`、`GET /contracts/{id}`、`PUT /contracts/{id}/rules`、`PUT /contracts/{id}/status`、`DELETE /contracts/{id}`、`POST /contracts/{id}/extract`、`GET /contracts/{id}/extract-status`、`GET /contracts/{id}/download`、`GET /business-types` |
| BI 考勤 | `POST /bi/upload`、`GET /bi/history` |
| 报告 | `GET /reports`、`POST /reports/generate`、`GET /reports/{id}/download` |

---

## Excel 模板要求

系统对上传的 Excel **按工作表别名匹配**，不要求固定文件名或固定表头文案，因此命名可灵活。

**项目基础资料（岗位 / 排班）** 期望包含以下工作表（别名均可识别）：

- 基础信息：`基础信息` / `项目基础信息` / `Sheet1`
- 合同编制表：`合同编制表` / `编制表` / `Sheet2`
- 月度排班表：`排班表` / `排班` / `排班情况` / `考勤表` / `月度排班` / `班次` / `考勤`
- 班次标准：模板内置

**BI 考勤** 期望工作表 `BI考勤`，列名支持宽松识别（如 `日期/考勤日期`、`姓名/人员姓名`、`打卡时间/打卡记录`）。

> 标准空白模板可由 `GET /api/v2/templates/project_base`（项目基础资料）与 `GET /api/v2/templates/attendance`（BI考勤）下载（前端「模板下载」入口）。

---

## Docker 部署（推荐）

在仓库根目录执行：

```bash
docker-compose up -d --build
```

启动三个服务（compose 项目 `audit-platform`）：

- `audit-mysql`：MySQL 8.0，宿主机 `3307 → 3306`，库名 `property_audit`
- `audit-backend`：Uvicorn，`app.main:app`，容器内 `8000`
- `audit-frontend`：Nginx 托管前端，**容器内 `80`，映射宿主机 `8080`**，前端 base 路径 `/audit/`

访问方式：

- 直接访问容器：`http://<服务器IP>:8080/audit/`
- 若服务器已有宿主 Nginx 在 80 端口、将 `/audit/`、`/api/`、`/files/` 反代到 `127.0.0.1:8080`（参见 `frontend/nginx.conf` 的路由约定），则访问 `http://<服务器IP>/audit/`

常用运维：

```bash
docker-compose ps
docker-compose logs -f backend
docker-compose restart backend
docker-compose up -d --build   # 更新代码后重建
docker image prune -f          # 清理旧镜像
```

> 迁移 / 上线说明、增量热部署等见团队内部部署记录（`DEPLOY.md`）。注意 `DEPLOY.md` 中仍有旧的“SQLite / `/api/` 根路径”描述，与当前 MySQL + `/audit/` 实际架构不一致，以本 README 与 `docker-compose.yml`、`frontend/nginx.conf` 为准。

---

## 实现说明与已知事项

- **审核引擎为确定性规则**：岗位缺编扣款来自「月度排班表」槽位 + 「合同编制表」；人员考勤扣款（迟到 / 早退 / 漏打卡 / 缺勤 / 工时不足 / 跨项目代班等）来自 BI 考勤 + 排班上下文。审核结果 `ai_analysis` 字段当前**预留、未填充 LLM 内容**，报告为模板生成（summary 报告名称为「审核汇总与扣款报告」）。
- **合同 LLM 提取 Agent 未启用**：`app/agent/graph.py`（LangGraph，视觉 + LLM 提取扣款参数）已实现，但未被任何 service / controller 引用，生产合同解析仍走 `pdf_parser` / `word_parser`（正则 + Tesseract OCR）。OCR 错字映射集中在解析器内，模板变动较大时提取率受限。
- **报告保留期**：启动时会清理超过 21 天的过期报告，避免磁盘堆积。
- **历史前端残留**：部分前端页面仍调用 `/api/v1/...` 路由（如 `Dashboard`、`BiSync`），但后端仅提供 `/api/v2`，这些调用会 404，属历史残留、请勿依赖。
- **BI 解析较脆弱**：`utils/excel_attendance_parser.py` 依赖列位置推断，`utils/bi_mapping.py` 含项目路径硬编码字典；考勤导出格式或路径变更可能导致整批解析失败，需相应调整解析器。
