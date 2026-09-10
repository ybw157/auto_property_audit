import base64
import asyncio
import io
import json
import re

import pypdfium2 as pdfium
from langgraph.graph import StateGraph, END, START

from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from app.agent.state import ContractAgentState
from app.agent.llm_config import llm_factory
from app.agent.models import ContractAuditParams, ContractMetadata

OCR_PROMPT = """请提取这张合同页面中的所有文字内容，保持原有格式和排版。
要求：
1. 完整输出所有文字，不要遗漏任何内容
2. 保留表格结构（用 | 分隔列，用换行分隔行）
3. 保留标题层级和段落结构
4. 只输出文字内容，不要添加任何解释或说明"""

METADATA_EXTRACT_PROMPT = """你是一个合同审核专家。请从以下合同首页图片中提取合同的基本元数据信息。

请输出一个 JSON 对象，包含以下字段（只输出 JSON，不要包含其他文字）：

{
  "project_name": "项目名称",
  "business_type": "业务类型（住宅/商业/物业/酒店/街区/写字楼/保洁/保安等）",
  "supplier": "供应商/乙方名称",
  "contract_no": "合同编号",
  "contract_name": "合同名称/标题",
  "service_type": "服务类型（保洁/保安/其他）",
  "version": "版本号",
  "start_date": "合同开始日期",
  "end_date": "合同结束日期"
}

提取规则：
1. 尽量从合同首页中提取所有可见的信息
2. 如果某个字段在合同中没有明确提及，设为 null
3. 日期格式统一为 YYYY-MM-DD
4. 只输出 JSON，不要包含任何其他文字"""

DEDUCTION_KEYWORDS = [
    "违约扣款", "扣款清单", "罚款", "违约金", "扣款标准",
    "服务不合格", "考核扣款", "处罚", "赔偿", "扣除",
    "迟到", "早退", "漏打卡", "缺勤", "旷工",
    "考勤管理", "出勤", "打卡",
]

LOCATE_PROMPT = """你是一个合同审核专家。以下是合同某一页的 OCR 文字内容。

请判断这一页是否包含与"违约扣款/罚款/考勤扣款/服务不合格扣款"相关的内容（通常是表格形式）。
只需回答"是"或"否"，不要输出其他内容。"""

EXTRACT_SYSTEM_PROMPT = """你是一个专业的合同审核专家。请从以下合同页面图片中提取结构化的扣款参数。

这些页面来自合同的"违约扣款清单"或类似的扣款附件表格。

请输出一个 JSON 对象，包含以下字段（只输出 JSON，不要包含其他文字）：

{
  "late_early_tiers": [
    {"max_minutes": 30, "deduction": 20, "description": "迟到或早退30分钟以内"},
    {"max_minutes": 60, "deduction": 50, "description": "迟到或早退1小时以内"}
  ],
  "late_early_over_minutes_as_absence": null,
  "missing_clock_deduction": 50,
  "missing_clock_free_times_per_month": 3,
  "missing_clock_free_requires_attendance_proof": true,
  "contract_deduction_coefficient": null,
  "attendance_deduction_coefficient": null,
  "late_grace_minutes": null,
  "early_leave_grace_minutes": null,
  "required_clock_count": 3,
  "minimum_work_hour_ratio": null,
  "single_person_daily_cap": null,
  "raw_deduction_text": "此处放扣款条款的原文摘录，用于留底备查"
}

提取规则：
1. late_early_tiers：从表格中提取迟到/早退的阶梯扣款，每个阶梯包含 max_minutes（最大分钟数）、deduction（扣款金额元）、description（说明）
2. late_early_over_minutes_as_absence：超过多少分钟算旷工/缺勤
3. missing_clock_deduction：漏打卡每次扣多少元
4. missing_clock_free_times_per_month：每月漏打卡免扣次数
5. missing_clock_free_requires_attendance_proof：免扣是否需要出勤证明（布尔值）
6. contract_deduction_coefficient：合同扣款系数（如有）—— S01/S04-4 缺勤缺岗扣款 = 工时单价 × 该系数 × 缺勤总时长
7. attendance_deduction_coefficient：考勤扣款系数（如有）
8. late_grace_minutes：迟到宽限分钟数（如有）
9. early_leave_grace_minutes：早退宽限分钟数（如有）
10. required_clock_count：每日要求打卡次数（如有）
11. minimum_work_hour_ratio：最低工时比（如有）
12. single_person_daily_cap：单人单日扣款上限（如有）
13. raw_deduction_text：扣款条款原文摘录（把表格中关键的扣款标准文字抄录下来）

注意：
- 如果某个字段在图片中没有提及，设为 null
- 金额保留原始数值，不要自行换算
- 阶梯扣款要完整提取所有阶梯
- 只输出 JSON，不要包含任何其他文字"""


async def load_pdf_node(state: ContractAgentState) -> dict:
    pdf_path = state["pdf_path"]
    pdf = pdfium.PdfDocument(pdf_path)
    pages_base64 = []

    for i in range(len(pdf)):
        page = pdf[i]
        bitmap = page.render(scale=200 / 72)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
        pages_base64.append(b64_str)

    page_count = len(pages_base64)
    pdf.close()

    return {
        "pdf_pages": pages_base64,
        "pdf_page_count": page_count,
    }


async def extract_metadata_node(state: ContractAgentState) -> dict:
    pdf_pages: list[str] = state.get("pdf_pages") or []
    if not pdf_pages:
        return {"contract_metadata": ContractMetadata(), "error": "no_pdf_pages"}

    llm = llm_factory.create("qwen3.7-plus", max_tokens=1024)

    first_page = pdf_pages[0]
    msg = HumanMessage(content=[
        {"type": "text", "text": METADATA_EXTRACT_PROMPT},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{first_page}"}},
    ])
    response = await llm.ainvoke([msg])
    raw_content = response.content or ""

    json_match = re.search(r"\{[\s\S]*}", raw_content)
    if json_match:
        raw_content = json_match.group(0)

    try:
        metadata = ContractMetadata.model_validate_json(raw_content)
    except (json.JSONDecodeError, ValidationError):
        cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw_content)
        try:
            metadata = ContractMetadata.model_validate_json(cleaned)
        except (json.JSONDecodeError, ValidationError):
            metadata = ContractMetadata()

    return {"contract_metadata": metadata}


async def _ocr_single_page(
    llm,
    b64_img: str,
    page_num: int,
    semaphore: asyncio.Semaphore,
) -> dict:
    async with semaphore:
        msg = HumanMessage(content=[
            {"type": "text", "text": OCR_PROMPT},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_img}"}},
        ])
        response = await llm.ainvoke([msg])
        return {"page": page_num, "text": response.content}


async def ocr_extract_node(state: ContractAgentState) -> dict:
    pages: list[str] = state["pdf_pages"]  # type: ignore[assignment]
    llm = llm_factory.create("qwen3.7-plus")
    semaphore = asyncio.Semaphore(3)

    tasks = [
        _ocr_single_page(llm, b64_img, i + 1, semaphore)
        for i, b64_img in enumerate(pages)
    ]
    ocr_pages = await asyncio.gather(*tasks)

    ocr_pages.sort(key=lambda x: x["page"])

    ocr_text_parts = []
    for page in ocr_pages:
        ocr_text_parts.append(f"\n\n--- 第 {page['page']} 页 ---\n\n")
        ocr_text_parts.append(page["text"])

    return {
        "ocr_text": "".join(ocr_text_parts),
        "ocr_pages": ocr_pages,
    }


async def locate_deduction_pages_node(state: ContractAgentState) -> dict:
    ocr_pages = state.get("ocr_pages") or []
    if not ocr_pages:
        return {"deduction_page_indices": [], "error": "no_ocr_pages"}

    llm = llm_factory.create("qwen3.7-plus", max_tokens=10)
    semaphore = asyncio.Semaphore(3)

    async def _check_page(page_info: dict, sem: asyncio.Semaphore) -> dict:
        async with sem:
            page_text = page_info.get("text", "")
            if not page_text:
                return {"page": page_info["page"], "is_deduction": False}

            keyword_hit = any(kw in page_text for kw in DEDUCTION_KEYWORDS)
            if not keyword_hit:
                return {"page": page_info["page"], "is_deduction": False}

            msg = HumanMessage(content=[
                {"type": "text", "text": LOCATE_PROMPT + "\n\n--- 页面文字 ---\n" + page_text},
            ])
            response = await llm.ainvoke([msg])
            answer = (response.content or "").strip().lower()
            is_deduction = "是" in answer or "yes" in answer
            return {"page": page_info["page"], "is_deduction": is_deduction}

    tasks = [_check_page(p, semaphore) for p in ocr_pages]
    results = await asyncio.gather(*tasks)

    deduction_indices = sorted([
        r["page"] - 1 for r in results if r["is_deduction"]
    ])

    if not deduction_indices:
        return {"deduction_page_indices": [], "error": "no_deduction_pages_found"}

    return {"deduction_page_indices": deduction_indices}


async def extract_deduction_params_node(state: ContractAgentState) -> dict:
    deduction_indices = state.get("deduction_page_indices") or []
    pdf_pages = state.get("pdf_pages") or []

    if not deduction_indices or not pdf_pages:
        return {
            "audit_params": ContractAuditParams(raw_deduction_text="未找到扣款相关页面"),
            "error": state.get("error", "no_deduction_pages"),
        }

    llm = llm_factory.create("qwen3.7-plus", max_tokens=4096)

    target_pages = []
    for idx in deduction_indices:
        if 0 <= idx < len(pdf_pages):
            target_pages.append((idx + 1, pdf_pages[idx]))

    if not target_pages:
        return {
            "audit_params": ContractAuditParams(raw_deduction_text="扣款页面图片获取失败"),
            "error": "deduction_page_images_missing",
        }

    content_parts: list[dict] = [
        {"type": "text", "text": EXTRACT_SYSTEM_PROMPT},
    ]
    for page_num, b64_img in target_pages:
        content_parts.append({
            "type": "text",
            "text": f"\n\n--- 第 {page_num} 页 ---\n",
        })
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64_img}"},
        })

    msg = HumanMessage(content=content_parts)
    response = await llm.ainvoke([msg])
    raw_content = response.content or ""

    json_match = re.search(r"\{[\s\S]*}", raw_content)
    if json_match:
        raw_content = json_match.group(0)

    try:
        params = ContractAuditParams.model_validate_json(raw_content)
    except (json.JSONDecodeError, ValidationError):
        cleaned = re.sub(r"[\x00-\x1f\x7f-\x9f]", "", raw_content)
        try:
            params = ContractAuditParams.model_validate_json(cleaned)
        except (json.JSONDecodeError, ValidationError):
            params = ContractAuditParams(
                raw_deduction_text=f"解析失败，原始输出: {raw_content[:500]}"
            )

    return {"audit_params": params}


def build_contract_agent_graph() -> StateGraph:
    workflow = StateGraph(ContractAgentState)  # type: ignore[type-var]

    workflow.add_node("load_pdf", load_pdf_node)  # type: ignore[arg-type]
    workflow.add_node("extract_metadata", extract_metadata_node)  # type: ignore[arg-type]
    workflow.add_node("ocr_extract", ocr_extract_node)  # type: ignore[arg-type]
    workflow.add_node("locate_deduction_pages", locate_deduction_pages_node)  # type: ignore[arg-type]
    workflow.add_node("extract_deduction_params", extract_deduction_params_node)  # type: ignore[arg-type]

    workflow.add_edge(START, "load_pdf")
    workflow.add_edge("load_pdf", "extract_metadata")
    workflow.add_edge("extract_metadata", "ocr_extract")
    workflow.add_edge("ocr_extract", "locate_deduction_pages")
    workflow.add_edge("locate_deduction_pages", "extract_deduction_params")
    workflow.add_edge("extract_deduction_params", END)

    return workflow


def compile_contract_agent():
    workflow = build_contract_agent_graph()
    # memory = MemorySaver()
    return workflow.compile()


contract_agent = compile_contract_agent()
