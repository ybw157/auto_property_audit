from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.core.database import get_conn

router = APIRouter()

class ConfigUpdate(BaseModel):
    value: str

@router.get("/config/rules")
def list_rule_configs():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rule_configs ORDER BY group_name,key").fetchall()
        return [dict(row) for row in rows]

@router.put("/config/rules/{rule_key}")
def update_rule_config(rule_key: str, payload: ConfigUpdate):
    with get_conn() as conn:
        row = conn.execute("SELECT key FROM rule_configs WHERE key=?", (rule_key,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="配置不存在")
        conn.execute("UPDATE rule_configs SET value=? WHERE key=?", (payload.value, rule_key))
    return {"key": rule_key, "value": payload.value}

@router.get("/config/attendance-deductions")
def attendance_deduction_configs():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM rule_configs WHERE group_name='扣款参数' ORDER BY key").fetchall()
        return [dict(row) for row in rows]
