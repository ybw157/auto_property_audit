from urllib.parse import unquote
from fastapi import APIRouter, Header
from app.core.database import get_conn, json_loads

router = APIRouter()


def _normalize_role(value: str) -> str:
    value = unquote(str(value or ""))
    return "项目账号" if value in {"项目账号", "project_user"} else "集团管理员"


def _decode(value: str) -> str:
    return unquote(str(value or ""))


@router.get("/dashboard/summary")
def dashboard_summary(x_user_role: str = Header("集团管理员"), x_project_name: str = Header("")):
    """首页汇总。集团管理员看全部已确认最终版；项目账号只看本项目的。"""
    role = _normalize_role(x_user_role)
    project = _decode(x_project_name)

    with get_conn() as conn:
        if role == "项目账号" and project:
            rows = conn.execute(
                """
                SELECT id,project_name,project_code,business_type,audit_month,status,is_locked,
                       summary_json,finished_at,confirmed_at
                FROM audit_batches
                WHERE project_name=? AND (status='已确认' OR IFNULL(is_locked,0)=1)
                ORDER BY id DESC
                """,
                (project,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id,project_name,project_code,business_type,audit_month,status,is_locked,
                       summary_json,finished_at,confirmed_at
                FROM audit_batches
                WHERE status='已确认' OR IFNULL(is_locked,0)=1
                ORDER BY id DESC
                """
            ).fetchall()

    # 去重：同一项目+月份只保留最新一条
    final_rows = []
    seen = set()
    for row in rows:
        key = (row["project_name"] or "", row["audit_month"] or "", row["business_type"] or "")
        if key in seen:
            continue
        seen.add(key)
        final_rows.append(row)

    total = len(final_rows)
    shortage = 0
    exception_count = 0
    deduction_amount = 0.0

    # 明细列表
    details = []
    for row in final_rows:
        summary = json_loads(row["summary_json"], {})
        s_shortage = int(summary.get("shortage_count", 0) or 0)
        s_exception = int(summary.get("exception_count", 0) or 0)
        s_deduction = float(summary.get("total_deduction_amount", 0) or 0)
        s_schedule = int(summary.get("schedule_task_count", 0) or 0)
        shortage += s_shortage
        exception_count += s_exception
        deduction_amount += s_deduction
        details.append({
            "batch_id": row["id"],
            "project_name": row["project_name"] or "",
            "business_type": row["business_type"] or "",
            "audit_month": row["audit_month"] or "",
            "status": row["status"] or "",
            "schedule_count": s_schedule,
            "shortage_count": s_shortage,
            "exception_count": s_exception,
            "deduction_amount": round(s_deduction, 2),
            "exception_rate": round((s_exception / s_schedule * 100) if s_schedule else 0, 1),
            "finished_at": row["finished_at"] or "",
            "confirmed_at": row["confirmed_at"] or "",
        })

    return {
        "monthly_project_count": total,
        "shortage_count": shortage,
        "exception_count": exception_count,
        "deduction_amount": round(deduction_amount, 2),
        "completion_rate": round((total / total * 100) if total else 0, 2),
        "details": details,
        "role": role,
        "project_name": project,
    }
