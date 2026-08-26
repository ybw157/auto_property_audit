from fastapi import APIRouter, Query
from app.core.database import get_conn, json_loads

router = APIRouter()

@router.get("/logs")
def list_logs(batch_id: int | None = Query(None), scope_type: str | None = Query(None)):
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    args = []
    if batch_id:
        sql += " AND audit_batch_id=?"
        args.append(batch_id)
    if scope_type:
        sql += " AND scope_type=?"
        args.append(scope_type)
    sql += " ORDER BY id DESC LIMIT 500"
    with get_conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    data = []
    for row in rows:
        item = dict(row)
        item["input"] = json_loads(item.pop("input_json"), {})
        item["output"] = json_loads(item.pop("output_json"), {})
        data.append(item)
    return data
