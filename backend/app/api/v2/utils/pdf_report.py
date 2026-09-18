"""V2 PDF 报告生成器（旧版样式迁移层）。

本文件不再自行实现报告排版，而是把新流水线数据交给 report_adapter 适配成
旧版 pdf_report_old 所需的 results 结构，再调用旧版函数生成 PDF，确保报告
的样式与逻辑与旧版代码仓完全一致：

  - build_attendance_detail_pdf  → 旧版 build_attendance_base_pdf   （考勤明细：打卡列含实际 BI 考勤）
  - build_summary_report_pdf     → 旧版 build_combined_report_pdf   （AI 审核汇总与扣款报告，对应桌面 PDF 样式）

【按服务类型（保安 / 保洁）分章】：
报告内容严格按服务类型区分——同一项目下每个 service_type（保安、保洁…）各成
独立章节（含服务项目、人员配置、工时、费用），章节间分页、互不混淆；报告标题
与导航行清晰标注所含服务类型。分章轴取项目的 audit_results.service_type（系统
正是按该字段分行存储审核结果），每章使用对应服务类型自身的审核结果，确保
费用 / 扣款 / 审核结论按服务类型独立呈现。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, SimpleDocTemplate, Paragraph, Spacer

from app.api.v2.core.config import settings
from app.api.v2.utils.pdf_report_old import (
    build_attendance_base_pdf,
    build_combined_report_pdf,
    build_service_chapter,
    build_service_attendance_chapter,
    styles,
    format_audit_month,
)
from app.api.v2.utils.report_adapter import adapt_to_old_results
from app.api.v2.dao import position_dao, bi_dao, contract_dao


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
    """把生成的报告文件名加上 audit_month（考勤明细_202608.pdf），

    重命名磁盘文件并同步 file_path 与 download_url，避免不同审核月份
    生成同名报告时互相覆盖（原文件名固定不含月份）。
    """
    old_path = Path(info["file_path"])
    new_path = old_path.with_name(f"{old_path.stem}_{audit_month}{old_path.suffix}")
    if new_path.exists():
        new_path.unlink()  # 同月重新生成时先删除旧文件
    old_path.rename(new_path)
    info["file_path"] = str(new_path)
    info["download_url"] = _make_download_url(new_path)
    return info


# ─────────────────────── 服务类型划分与数据过滤 ───────────────────────

def _classify_service(pos: dict) -> str:
    """根据岗位的 职位归属(position_type) 或岗位名关键字判定服务类型。

    position_type 的实际取值是「保洁岗 / 安保岗 / 保安员 / 管理岗 …」而非裸的
    「保洁 / 保安」，因此先去掉「岗/员/队」等后缀再判定，避免全部分组落空。
    """
    pt = str(pos.get("position_type") or "").strip()
    pn = str(pos.get("position_name") or "")
    for field_ in (pt, pn):
        cleaned = re.sub(r"[岗员队工]", "", field_)
        if "保安" in cleaned or "安保" in cleaned or "安管" in cleaned:
            return "保安"
        if "保洁" in cleaned or "清洁" in cleaned:
            return "保洁"
    return "其他"


def _group_positions_by_service(position_data: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for p in (position_data or []):
        groups.setdefault(_classify_service(p), []).append(p)
    return groups


def _employees_of_positions(position_data: list[dict]) -> set[str]:
    """收集一组岗位下的全部员工姓名（用于按服务类型裁剪 BI 与异常数据）。"""
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
    """按岗位名集合裁剪审核结果 JSON，使某一服务类型的章节只含其自身数据。

    同时丢弃 final_summary（混合态聚合值），让报告按裁剪后的明细重新聚合计费，
    保证每章的总扣款/异常数均为该服务类型独立口径。
    """
    pos_names = set(pos_names or set())
    if not pos_names or not isinstance(audit_results, dict):
        return audit_results
    ar = dict(audit_results)
    s04 = dict(ar.get("s04_attendance_audit", {}) or {})
    s04["deduction_details"] = [
        d for d in (s04.get("deduction_details") or [])
        if (d.get("position") or "") in pos_names
    ]
    s04_summary = dict(s04.get("summary") or {})
    s04_summary["affected_employees"] = len({
        d.get("employee_name") for d in s04["deduction_details"]
    })
    s04["summary"] = s04_summary
    ar["s04_attendance_audit"] = s04
    ar["summary"] = [x for x in (ar.get("summary") or []) if (x.get("position") or "") in pos_names]
    ar["slot_details"] = [x for x in (ar.get("slot_details") or []) if (x.get("position") or "") in pos_names]
    ar.pop("final_summary", None)
    return ar


# ─────────────────────── 多服务类型章节编排 ───────────────────────

# 服务类型章节的展示顺序：保安、保洁 优先，其余按出现顺序。
_SERVICE_PRIORITY = {"保安": 0, "保洁": 1}


def _normalize_audit_input(audit_input):
    """兼容两种入参：
    - 单个 results dict → 视为单一「全部服务」章节；
    - [{"service_type": str, "results": dict}, ...] → 按服务类型分章。
    """
    if isinstance(audit_input, dict):
        return [{"service_type": "", "results": audit_input}]
    return list(audit_input)


def _chapter_label(service_type: str) -> str:
    st = (service_type or "").strip()
    return st if st else "全部服务"


def _build_multi_service_pdf(
    kind: str,
    title: str,
    project_name: str,
    business_type: str,
    audit_month: str,
    audit_input,
    report_dir: Path,
    contract: dict | None = None,
) -> dict:
    """生成一份按服务类型（保安/保洁）分章的 PDF。

    kind="attendance" → 考勤明细（每日打卡网格）；
    kind="combined"   → AI 审核汇总与扣款报告。
    """
    position_info = position_dao.get_position_info(project_name, business_type, audit_month)
    position_data_all = (
        [p.to_dict() for p in position_info.positions]
        if position_info and position_info.positions else []
    )
    bi_records = bi_dao.get_bi_by_project(audit_month, project_name)

    audit_items = _normalize_audit_input(audit_input)
    # 去重 service_type，保持顺序
    seen = set()
    raw_types: list[str] = []
    for it in audit_items:
        st = (it.get("service_type") or "").strip()
        if st not in seen:
            seen.add(st)
            raw_types.append(st)
    ordered_types = sorted(raw_types, key=lambda t: (_SERVICE_PRIORITY.get(t, 9), t))

    s = styles()
    st_labels = [_chapter_label(t) for t in ordered_types]
    st_label = "、".join(st_labels)
    file_path = report_dir / f"{title}.pdf"
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm, topMargin=12*mm, bottomMargin=12*mm,
    )
    story = [Paragraph(title, s["CNTitle"])]
    story.append(Paragraph(
        f"{project_name}（{business_type}）｜{format_audit_month(audit_month)}｜"
        f"服务类型：{st_label}｜生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
        s["CNBody"],
    ))
    story.append(Spacer(1, 4))
    nav = "　".join(f"第{i+1}部分 {lab}服务" for i, lab in enumerate(st_labels))
    story.append(Paragraph("报告按服务类型分章呈现，各章数据独立、互不混淆：" + nav, s["CNNote"]))
    story.append(Spacer(1, 10))

    for idx, st in enumerate(ordered_types, start=1):
        item = next(it for it in audit_items if (it.get("service_type") or "").strip() == st)
        results_data = item.get("results") or {}

        # 岗位子集：先取该服务类型自己的排班记录（库里已按 service_type 分行存储），
        # 再按岗位归类裁剪；两者都取不到时才回退到全量岗位（兼容改造前的历史数据）。
        pi_st = position_dao.get_position_info(project_name, business_type, audit_month, st or "")
        pos_data_st = (
            [p.to_dict() for p in pi_st.positions]
            if pi_st and pi_st.positions else []
        )
        groups = _group_positions_by_service(pos_data_st or position_data_all)
        pos_subset = groups.get(st) or pos_data_st or position_data_all
        emp_subset = _employees_of_positions(pos_subset)
        bi_subset = (
            _filter_bi_by_employees(bi_records, emp_subset)
            if pos_subset is not position_data_all else bi_records
        )
        c = contract_dao.get_latest_active_contract(project_name, business_type, service_type=st)
        if c is not None:
            contract_st = {
                "contract_no": getattr(c, "contract_no", ""),
                "supplier": getattr(c, "supplier", ""),
                "contract_name": getattr(c, "contract_name", "未匹配"),
            }
        else:
            contract_st = contract or {}

        ar_subset = (
            filter_audit_results_by_positions(
                results_data, {p.get("position_name", "") for p in pos_subset}
            )
            if pos_subset is not position_data_all else results_data
        )
        results_st = adapt_to_old_results(
            project_name=project_name,
            business_type=business_type,
            audit_month=audit_month,
            bi_records=bi_subset,
            position_data=pos_subset,
            audit_results=ar_subset,
            contract=contract_st,
            kind=kind,
        )
        if idx > 1:
            story.append(PageBreak())
        label = _chapter_label(st)
        if kind == "combined":
            build_service_chapter(story, results_st, pos_subset, label, s, idx)
        else:
            build_service_attendance_chapter(story, results_st, label, s, idx)

    doc.build(story)
    info = {
        "report_type": title,
        "file_format": "pdf",
        "file_path": str(file_path),
        "download_url": f"/files/reports/0/{title}.pdf",
    }
    return _finalize_report_info(info, audit_month)


def build_attendance_detail_pdf(
    project_name: str,
    business_type: str,
    audit_month: str,
    audit_input,
    report_dir: Path,
    contract: dict | None = None,
) -> dict:
    """考勤明细 PDF —— 旧版 build_attendance_base_pdf 样式（按服务类型分章）。
    打卡列展示实际 BI 考勤记录。"""
    return _build_multi_service_pdf(
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
) -> dict:
    """AI 审核汇总与扣款报告 PDF —— 旧版 build_combined_report_pdf 样式（按服务类型分章）。"""
    return _build_multi_service_pdf(
        "combined", "AI审核汇总与扣款报告", project_name, business_type, audit_month,
        audit_input, report_dir, contract,
    )
