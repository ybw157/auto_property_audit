# 物业集团保安保洁智能审核平台

这是一个完整的网站项目，采用 React + TypeScript + Tailwind CSS + FastAPI 架构，用于集团级保安保洁外包履约和人员考勤扣款审核。

## 功能范围

- 上传 `项目基础资料.xlsx` 与 `BI考勤.xlsx`
- 按 Sheet 名称读取项目基础信息、合同编制表、月度排班表、班次标准
- 执行合同履约审核，计算岗位缺编扣款
- 执行人员考勤审核，计算迟到、早退、漏打卡、缺勤、工时不足等扣款
- 生成审核 Excel
- 生成 PDF 报告
- 生成 AI 分析总结
- 记录岗位、人员、规则、报告生成全过程日志
- 支持集团所有项目共用同一套规则逻辑

## 技术栈

| 模块 | 技术 |
|---|---|
| 前端 | React + TypeScript + Vite + Tailwind CSS |
| 后端 | Python + FastAPI |
| 数据库 | SQLite，保留 PostgreSQL 迁移空间 |
| Excel | openpyxl |
| PDF | ReportLab |
| 审核逻辑 | Rule Engine |

## 启动后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端默认访问后端地址：`http://localhost:8000`。

## Excel模板要求

`项目基础资料.xlsx` 必须包含以下 Sheet：

- 项目基础表
- 保洁人员实际在岗编制表
- 月度排班表

不再使用 `人员调整表`。系统按你提供的项目基础资料模板读取，月度排班表为最终排班依据。

`BI考勤.xlsx` 支持字段名称的宽松识别，例如 `日期/考勤日期`、`姓名/人员姓名`、`打卡时间/打卡记录`。

## 关键规则

- 合同履约审核影响岗位缺编扣款
- 人员考勤审核影响人员异常扣款
- 两类扣款分开计算、分开展示、合并汇总
- AI只读取审核结果生成管理分析，不参与最终计算
