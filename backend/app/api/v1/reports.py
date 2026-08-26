from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from app.core.database import get_conn, json_loads, now_text
from app.services.report_generator.excel_report import generate_excel_report
from app.services.report_generator.pdf_report import generate_pdf_report

router = APIRouter()

@router.post("/reports/{batch_id}/excel")
def create_excel_report(batch_id: int):
    results = _get_results(batch_id)
    report = generate_excel_report(batch_id, results)
    _save_report(batch_id, "综合审核结果", "xlsx", report)
    return report

@router.post("/reports/{batch_id}/pdf")
def create_pdf_report(batch_id: int):
    results = _get_results(batch_id)
    reports = generate_pdf_report(batch_id, results)
    for report in reports:
        _save_report(batch_id, report["report_type"], "pdf", report)
    return reports

@router.get("/reports/{batch_id}")
def list_reports(batch_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generated_reports WHERE audit_batch_id=? AND (report_type LIKE '%考勤明细' OR report_type LIKE '%AI审核汇总与扣款报告') ORDER BY id DESC",
            (batch_id,),
        ).fetchall()
        return [dict(row) for row in rows]

@router.get("/reports/{report_id}/download")
def download_report(report_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM generated_reports WHERE id=?", (report_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="报告不存在")
    return FileResponse(row["file_path"], filename=row["file_path"].split("\\")[-1])

def _get_results(batch_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT results_json FROM audit_batches WHERE id=?", (batch_id,)).fetchone()
        if not row or not row["results_json"]:
            raise HTTPException(status_code=400, detail="请先完成审核")
        return json_loads(row["results_json"], {})

def _save_report(batch_id: int, report_type: str, file_format: str, report: dict):
    with get_conn() as conn:
        # 先删除同批次同类型的旧报告，避免重复
        conn.execute(
            "DELETE FROM generated_reports WHERE audit_batch_id=? AND report_type=? AND file_format=?",
            (batch_id, report_type, file_format),
        )
        conn.execute(
            "INSERT INTO generated_reports(audit_batch_id,report_type,file_format,file_path,download_url,created_at) VALUES(?,?,?,?,?,?)",
            (batch_id, report_type, file_format, report["file_path"], report["download_url"], now_text()),
        )
