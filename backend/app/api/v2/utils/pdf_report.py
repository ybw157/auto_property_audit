"""V2 PDF 报告生成器（旧版样式迁移层）。

本文件不再自行实现报告排版，而是把新流水线数据交给 report_adapter 适配成
旧版 pdf_report_old 所需的 results 结构，再调用旧版函数生成 PDF，确保报告
的样式与逻辑与旧版代码仓完全一致：

  - build_attendance_detail_pdf  → 旧版 build_attendance_base_pdf   （考勤明细：打卡列含实际 BI 考勤）
  - build_summary_report_pdf     → 旧版 build_combined_report_pdf   （AI 审核汇总与扣款报告，对应桌面 PDF 样式）

【按服务类型独立出报告】：
系统只有两种服务类型——保安、保洁。这两类服务各自独立处理，互不合并：

  - 每类服务单独生成一份 PDF，文件名带服务类型前缀区分，例如
    保安考勤明细_202608.pdf / 保洁考勤明细_202608.pdf /
    保安AI审核汇总与扣款报告_202608.pdf / 保洁AI审核汇总与扣款报告_202608.pdf；
  - 报告内容取该类服务自身的排班编制表、BI 考勤、合同与 audit_results.service_type
    对应的审核结果，费用 / 扣款 / 审核结论按服务类型完全分离；
  - 该类服务的岗位编制表缺失时直接报错终止，绝不借用另一类服务的数据。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

from app.api.v2.core.config import settings
from app.api.v2.utils.pdf_report_old import (
    build_service_chapter,
    build_service_attendance_chapter,
    styles,
    format_audit_month,
)
from app.api.v2.utils.report_adapter import adapt_to_old_results
from app.api.v2.utils.audit_common import recompute_audit_totals
from app.api.v2.dao import position_dao, bi_dao, contract_dao


# 系统只支持两种服务类型，报告的生成与命名都按此顺序进行。
SERVICE_TYPES = ("保安", "保洁")


def _norm(value) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _make_download_url(file_path: str | Path) -> str:
    """根据磁盘绝对路径推导 /files/... 静态访问 URL。

    后端将 settings.storage_dir 挂载为 /files，因此用 file_path 减去
    storage_dir 前缀即可得到相对 /files 的访问路径，并对含中文的
    目录/文件名做 URL 编码，保证可直接在浏览器或前端打开。
    """
    try:
        storage_root = Path(settings.storage_dir).resolve()
        rel = Path(file_path).resolve().relative_to(storage_root)
    except Exception:
        return ""
    encoded = "/".join(quote(part, safe="") for part in rel.parts)
    return f"/files/{encoded}"


def _finalize_report_info(info: dict, audit_month: str) -> dict:
    """把生成的报告文件名加上 audit_month（保安考勤明细_202608.pdf），

    重命名磁盘文件并同步 file_path 与 download_url，避免不同审核月份
    生成同名报告时互相覆盖。文件名本身已含服务类型标识（保安 / 保洁），
    因此不同服务类型的报告各有独立文件、可同时保存。
    """
    old_path = Path(info["file_path"])
    new_path = old_path.with_name(f"{old_path.stem}_{audit_month}{old_path.suffix}")
    if new_path.exists():
        new_path.unlink()  # 同服务类型同月重新生成时先删除旧文件
    old_path.rename(new_path)
    info["file_path"] = str(new_path)
    info["download_url"] = _make_download_url(new_path)
    return info


# ─────────────────────── 服务类型数据裁剪 ───────────────────────

def _classify_service(pos: dict) -> str:
    """根据岗位的 职位归属(position_type) 或岗位名关键字判定服务类型。

    position_type 的实际取值是「保洁岗 / 安保岗 / 保安员 / 管理岗 …」而非裸的
    「保洁 / 保安」，因此先去掉「岗/员/队」等后缀再判定。
    仅用于离线核查工具（tools/scan_service_types.py）对存量数据摸底，
    报告生成不走这里——报告一律以 audit_results.service_type 为准。
    """
    pt = str(pos.get("position_type") or "").strip()
    pn = str(pos.get("position_name") or "")
    for field_ in (pt, pn):
        cleaned = re.sub(r"[岗员队工]", "", field_)
        if "保安" in cleaned or "安保" in cleaned or "安管" in cleaned:
            return "保安"
        if "保洁" in cleaned or "清洁" in cleaned:
            return "保洁"
    return ""


def _group_positions_by_service(position_data: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for p in (position_data or []):
        groups.setdefault(_classify_service(p), []).append(p)
    return groups


def _employees_of_positions(position_data: list[dict]) -> set[str]:
    """收集一组岗位下的全部员工姓名（用于按服务类型裁剪 BI 考勤）。"""
    names: set[str] = set()
    for p in (position_data or []):
        for n in (p.get("staff_list") or []):
            nn = _norm(n)
            if nn:
                names.add(nn)
        for slot in (p.get("slots") or []):
            for cells in (slot.get("daily") or {}).values():
                for cell in cells:
                    for n in (cell.get("names") or []):
                        nn = _norm(n)
                        if nn:
                            names.add(nn)
    return names


def _filter_bi_by_employees(bi_records: list[dict], names: set[str]) -> list[dict]:
    return [r for r in (bi_records or []) if _norm(r.get("employee_name", "")) in names]


def filter_audit_results_by_positions(audit_results: dict, pos_names: set[str]) -> dict:
    """按岗位名集合裁剪审核结果 JSON，使某一服务类型的报告只含其自身数据。

    裁剪后按唯一「计入」规则就地重算该子集的 s04.summary，使报告的
    总扣款/异常数与明细行完全同源（不引入第二套口径）。
    """
    pos_names = set(pos_names or set())
    if not pos_names or not isinstance(audit_results, dict):
        return audit_results
    ar = dict(audit_results)
    s04 = dict(ar.get("s04_attendance_audit", {}) or {})
    # 复制每条 detail，避免下面的重算改到调用方的原始数据
    s04["deduction_details"] = [
        dict(d) for d in (s04.get("deduction_details") or [])
        if (d.get("position") or "") in pos_names
    ]
    ar["s04_attendance_audit"] = s04
    ar["summary"] = [x for x in (ar.get("summary") or []) if (x.get("position") or "") in pos_names]
    ar["slot_details"] = [x for x in (ar.get("slot_details") or []) if (x.get("position") or "") in pos_names]
    recompute_audit_totals(ar)
    return ar


# ─────────────────────── 单服务类型报告生成 ───────────────────────

def _service_positions(project_name: str, business_type: str, audit_month: str, service_type: str) -> list[dict]:
    """取该服务类型自己的岗位编制表；缺失即报错，不借用另一类服务的数据。"""
    info = position_dao.get_position_info(project_name, business_type, audit_month, service_type)
    if not info or not info.positions:
        raise ValueError(
            f"未找到「{service_type}」的岗位编制表"
            f"（项目：{project_name}｜业态：{business_type}｜月份：{audit_month}），无法生成报告"
        )
    return [p.to_dict() for p in info.positions]


def _build_service_report(
    kind: str,
    title: str,
    project_name: str,
    business_type: str,
    audit_month: str,
    service_type: str,
    results_data: dict,
    report_dir: Path,
    contract: dict | None = None,
) -> dict:
    """生成一份只含单一服务类型（保安 / 保洁）的 PDF。

    kind="attendance" → 考勤明细（每日打卡网格）；
    kind="combined"   → AI 审核汇总与扣款报告。
    文件名即报告类型标签带服务类型前缀（保安考勤明细 / 保洁考勤明细 …）。
    """
    positions = _service_positions(project_name, business_type, audit_month, service_type)

    bi_records = _filter_bi_by_employees(
        bi_dao.get_bi_by_project(audit_month, project_name),
        _employees_of_positions(positions),
    )

    c = contract_dao.get_latest_active_contract(project_name, business_type, service_type=service_type)
    if c is not None:
        contract_data = {
            "contract_no": getattr(c, "contract_no", ""),
            "supplier": getattr(c, "supplier", ""),
            "contract_name": getattr(c, "contract_name", "未匹配"),
        }
    else:
        contract_data = contract or {}

    results = filter_audit_results_by_positions(
        results_data, {p.get("position_name", "") for p in positions}
    )
    results_st = adapt_to_old_results(
        project_name=project_name,
        business_type=business_type,
        audit_month=audit_month,
        bi_records=bi_records,
        position_data=positions,
        audit_results=results,
        contract=contract_data,
        kind=kind,
    )

    report_name = f"{service_type}{title}"
    file_path = report_dir / f"{report_name}.pdf"
    s = styles()
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=12*mm, bottomMargin=12*mm,
    )
    story = [Paragraph(title, s["CNTitle"])]
    story.append(Paragraph(
        f"{project_name}（{business_type}）｜{format_audit_month(audit_month)}｜"
        f"服务类型：{service_type}｜生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        s["CNBody"],
    ))
    story.append(Spacer(1, 10))
    if kind == "combined":
        build_service_chapter(story, results_st, positions, service_type, s, 1)
    else:
        build_service_attendance_chapter(story, results_st, service_type, s, 1)
    doc.build(story)

    info = {
        "report_type": report_name,
        "file_format": "pdf",
        "file_path": str(file_path),
        "service_type": service_type,
    }
    return _finalize_report_info(info, audit_month)


def _build_reports(
    kind: str,
    title: str,
    project_name: str,
    business_type: str,
    audit_month: str,
    audit_input,
    report_dir: Path,
    contract: dict | None = None,
) -> list[dict]:
    """按服务类型（保安 / 保洁）分别生成报告，返回各自的报告信息列表。

    audit_input 形如 [{"service_type": "保安", "results": {...}}, ...]，
    来自 audit_results.service_type 分行存储的审核结果。

    服务类型缺失即报错，不再「不属于任何一类就跳过」：静默跳过会让用户以为
    报告已生成完毕，实际少了某一类的数据。服务类型必填是定位键的第四列。
    """
    results_by_type: dict[str, dict] = {}
    for item in (audit_input or []):
        st = (item.get("service_type") or "").strip()
        if not st:
            raise ValueError("缺少「服务类型」字段数据，无法生成报告")
        if st not in SERVICE_TYPES:
            raise ValueError(f"服务类型「{st}」不在支持范围内（{'、'.join(SERVICE_TYPES)}）")
        if st not in results_by_type:
            results_by_type[st] = item.get("results") or {}

    ordered = [st for st in SERVICE_TYPES if st in results_by_type]
    if not ordered:
        raise ValueError("未找到保安 / 保洁的审核结果，无法生成报告")

    # 先校验两类服务的编制表齐备，避免生成到一半才失败
    for st in ordered:
        _service_positions(project_name, business_type, audit_month, st)

    report_dir.mkdir(parents=True, exist_ok=True)
    return [
        _build_service_report(
            kind, title, project_name, business_type, audit_month,
            st, results_by_type[st], report_dir, contract,
        )
        for st in ordered
    ]


def build_attendance_detail_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    audit_input,
    report_dir: Path,
    contract: dict | None = None,
) -> list[dict]:
    """考勤明细 PDF —— 旧版 build_attendance_base_pdf 样式。

    保安、保洁各生成一份独立 PDF（保安考勤明细_月份.pdf / 保洁考勤明细_月份.pdf），
    打卡列展示各自服务类型的实际 BI 考勤记录。
    """
    return _build_reports(
        "attendance", "考勤明细", project_name, business_type, audit_month,
        audit_input, report_dir, contract,
    )


def build_summary_report_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    audit_input,
    report_dir: Path,
    contract: dict | None = None,
) -> list[dict]:
    """AI 审核汇总与扣款报告 PDF —— 旧版 build_combined_report_pdf 样式。

    同样按服务类型独立成文：保安AI审核汇总与扣款报告_月份.pdf /
    保洁AI审核汇总与扣款报告_月份.pdf。
    """
    return _build_reports(
        "combined", "AI审核汇总与扣款报告", project_name, business_type, audit_month,
        audit_input, report_dir, contract,
    )
