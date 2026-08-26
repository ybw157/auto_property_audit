from fastapi import APIRouter
from app.core.database import get_conn

router = APIRouter()

@router.get("/projects")
def list_projects():
    """返回项目主档列表（不受角色/已选项目过滤）。用于前端项目下拉框。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT project_name, project_code
            FROM project_business_types
            WHERE status='启用'
            ORDER BY project_name
            """
        ).fetchall()
    return [dict(row) for row in rows]

@router.get("/projects/{project_name}/business-types")
def list_project_business_types(project_name: str):
    """返回某个项目下的所有业态。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT project_name, project_code, business_type
            FROM project_business_types
            WHERE project_name=? AND status='启用'
            ORDER BY business_type
            """,
            (project_name,),
        ).fetchall()
    return [dict(row) for row in rows]
