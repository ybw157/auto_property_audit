"""PDF 合同解析器 —— 从 PDF 中提取文本并解析结构化扣款细则。

文字版 PDF 走 pypdf 文本层；扫描件走 OCR（ocr_pdf_text）：
优先调用 LLM 视觉模型识别（qwen3.7-plus，实测该 key 可用），
失败或未配置时回退本地 Tesseract，保持离线能力。
"""
import json
import logging
import os
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_contract_metadata(path: Path, original_name: str) -> dict:
    text = extract_contract_text(Path(path))
    source = f"{Path(original_name).stem}\n{text}"
    # 合同有效期：按用户口径只读『合同期限』这一行（不再依赖"自/从/起"前缀）
    start_date, end_date = extract_contract_period(source)
    result = {
        "project_name": extract_project_name(source),
        "business_type": extract_business_type(source),
        "supplier": extract_supplier(source),
        "contract_no": extract_first(source, [r"(?:合同编号|合同号)[:：\s]*([A-Za-z0-9_\-（）()第号]+)"]),
        "contract_name": Path(original_name).stem,
        "service_type": "保洁" if "保洁" in source else ("保安" if "保安" in source else "保洁"),
        "version": extract_first(source, [r"版本[:：\s]*([A-Za-z0-9_\-\.]+)"]),
        "start_date": start_date,
        "end_date": end_date,
        "rules": extract_contract_rules(source),
    }
    _log_parse_result(original_name, len(text), result)
    return result


def _log_parse_result(original_name: str, text_len: int, result: dict) -> None:
    """把解析出的每个字段完整打到日志，方便核对细则各字段是否提取正确。"""
    rules = result.get("rules") or {}
    field_labels = [
        ("project_name", "项目名称"),
        ("supplier", "供应商/乙方"),
        ("contract_no", "合同编号"),
        ("contract_name", "合同名称"),
        ("service_type", "服务类型"),
        ("business_type", "业态"),
        ("version", "版本"),
        ("start_date", "合同开始"),
        ("end_date", "合同结束"),
    ]
    lines = [f"[合同解析] ===== {original_name} 字段提取结果（全文 {text_len} 字）====="]
    for key, label in field_labels:
        lines.append(f"[合同解析]   {key}({label}) = {result.get(key)!r}")
    lines.append(f"[合同解析]   rules(扣款细则) 共 {len(rules)} 项:")
    if rules:
        for k, v in rules.items():
            lines.append(f"[合同解析]     - {k} = {json.dumps(v, ensure_ascii=False)}")
    else:
        lines.append("[合同解析]     (空：未提取到任何细则字段)")
    # 单条多行日志，避免多 worker 并发时与其它合同的日志交错
    logger.info("\n".join(lines))


def extract_contract_period(text: str) -> tuple[str, str]:
    """读『合同期限』这一行的两个日期（用户要求简化口径，不再依赖"自/从/起"前缀）。

    匹配优先级：
    1. 找第一行形如『合同期限：xxxx 至 xxxx』的内容
    2. 从该行内提取两个 YYYY-MM-DD 形式日期（OCR 场景日期常带空格，如"2025 年 12 月 1 日"）
    """
    m = re.search(r"合同期限[:：\s]*([^\n\r]{2,120})", text)
    if not m:
        return "", ""
    line = m.group(1)
    dates = re.findall(r"\d{4}\s*[年/\-.]\s*\d{1,2}\s*[月/\-.]\s*\d{1,2}", line)
    if len(dates) >= 2:
        return normalize_date_text(dates[0]), normalize_date_text(dates[1])
    return "", ""


def extract_contract_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        # 用 \f（form feed）分隔每页，extract_supplier 借此只读第一页乙方字段
        text = "\f".join(page.extract_text() or "" for page in reader.pages)
        # 显式关闭 reader 释放文件句柄，避免 Windows 下 os.replace 报 PermissionError
        reader.close()
        stripped = text.strip()
        meaningful_chars = len(
            stripped.replace("契约锁", "").replace(" ", "").replace("\n", "").replace("\r", "").replace("\f", "")
        )
        if len(stripped) < 200 or meaningful_chars < 100:
            logger.info(
                f"[合同解析] {path.name}: pypdf 文本层过短（总长 {len(stripped)} / 有效 {meaningful_chars} 字），"
                f"判定为扫描件 → 触发 OCR"
            )
            text = ocr_pdf_text(path)
        else:
            logger.info(f"[合同解析] {path.name}: pypdf 文本层提取成功（{len(stripped)} 字），无需 OCR")
        return text
    except Exception as e:
        logger.warning(f"PDF 文本提取失败，尝试 OCR: {e}")
        return ocr_pdf_text(path)


_LLM_OCR_PROMPT = (
    "请提取这张合同页面中的所有文字内容，保持原有格式和排版。\n"
    "要求：\n"
    "1. 完整输出所有文字，不要遗漏任何内容\n"
    "2. 保留表格结构（用 | 分隔列，用换行分隔行）\n"
    "3. 保留标题层级和段落结构\n"
    "4. 只输出文字内容，不要添加任何解释或说明"
)

# 该 API Key 实测可用链（2026-09-23 真实合同探针验证）：
# 专用 OCR 模型 qwen3.5-ocr / qwen-vl-ocr-latest / qwen3-vl-plus 均 403 未授权；
# glm-5.2 在此网关收不到图片；qwen3.7-plus 最快最准，qwen3.6-plus 可作降级。
_LLM_OCR_MODEL_CHAIN = ["qwen3.7-plus", "qwen3.6-plus"]


def ocr_pdf_text(path: Path) -> str:
    """OCR 入口（签名与职责不变）：优先 LLM 视觉识别，失败回退本地 Tesseract。

    环境变量：
    - LLM_API_KEY / LLM_BASE_URL：缺失时直接走 Tesseract（保持离线能力）
    - LLM_OCR_MODEL：钉死单一模型；缺省用经验证的降级链 qwen3.7-plus → qwen3.6-plus
    - LLM_OCR_WORKERS：并发页数，默认 3
    - LLM_OCR_TIMEOUT：单页超时秒数，默认 120
    - LLM_OCR_ENABLED=0：强制只用 Tesseract（应急开关）
    - LLM_OCR_SCALE：LLM 链路渲染倍率，默认 1.5（实测与 2.0 质量一致、快约 40%）
    - LLM_OCR_JPEG_QUALITY：LLM 链路图片 JPEG 质量，默认 85（体积较 PNG 降约 75%）
    """
    # LLM 可用时用 1.5x 渲染（快）；LLM 关闭/未配置时保持 2.0x（Tesseract 既有口径）
    llm_ready = (
        os.getenv("LLM_OCR_ENABLED", "1").strip().lower() not in ("0", "false", "no")
        and bool(os.getenv("LLM_API_KEY", "").strip())
        and bool(os.getenv("LLM_BASE_URL", "").strip())
    )
    scale = float(os.getenv("LLM_OCR_SCALE", "1.5") or "1.5") if llm_ready else 2.0
    images = _render_pdf_images(path, scale=scale)
    if not images:
        return ""
    logger.info(f"[合同解析] {path.name}: 开始 OCR，共 {len(images)} 页（渲染 {scale}x）")

    llm_pages = _ocr_pages_via_llm(images)
    if llm_pages is None:
        logger.info(f"[合同解析] {path.name}: OCR 引擎 = 本地 Tesseract（LLM 未启用或未配置），共 {len(images)} 页")
        return "\n".join(_ocr_pages_via_tesseract(images, range(len(images))))

    texts = list(llm_pages)
    fallback_idx = [i for i, t in enumerate(texts) if not t.strip()]
    if fallback_idx:
        logger.warning(f"[合同解析] {path.name}: LLM OCR 第 {[i + 1 for i in fallback_idx]} 页失败，回退 Tesseract")
        for i, t in zip(fallback_idx, _ocr_pages_via_tesseract(images, fallback_idx)):
            texts[i] = t
        logger.info(
            f"[合同解析] {path.name}: OCR 引擎 = 混合（LLM {len(images) - len(fallback_idx)} 页 + "
            f"Tesseract {len(fallback_idx)} 页）"
        )
    else:
        logger.info(f"[合同解析] {path.name}: OCR 引擎 = LLM 视觉模型，{len(images)}/{len(images)} 页全部成功")
    return "\n".join(texts)


def _render_pdf_images(path: Path, scale: float = 2.0) -> list:
    """把 PDF 每页渲染成 PIL 图片（两种 OCR 引擎共用）。

    scale 默认 2.0（Tesseract 口径）；LLM 链路走 LLM_OCR_SCALE（默认 1.5，
    实测与 2.0 识别质量一致、单页快约 40%）。
    """
    try:
        import pypdfium2 as pdfium

        # 使用 with 语句确保文件句柄被正确关闭
        with pdfium.PdfDocument(str(path)) as pdf:
            return [pdf[i].render(scale=scale).to_pil() for i in range(len(pdf))]
    except Exception as e:
        logger.error(f"PDF 渲染失败: {e}")
        return []


def _ocr_pages_via_llm(images: list) -> list | None:
    """逐页 LLM 视觉 OCR，返回与 images 等长的文本列表（失败页为 ""）。

    配置缺失 / openai 不可用 / 被 LLM_OCR_ENABLED=0 关闭时返回 None，
    由调用方整体回退 Tesseract。
    """
    if os.getenv("LLM_OCR_ENABLED", "1").strip().lower() in ("0", "false", "no"):
        logger.info("LLM_OCR_ENABLED=0，OCR 走本地 Tesseract")
        return None
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", "").strip()
    if not api_key or not base_url:
        logger.info("LLM_API_KEY/LLM_BASE_URL 未配置，OCR 回退本地 Tesseract")
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("未安装 openai 包，OCR 回退本地 Tesseract")
        return None

    import base64
    import io
    from concurrent.futures import ThreadPoolExecutor

    pin = os.getenv("LLM_OCR_MODEL", "").strip()
    models = [pin] if pin else list(_LLM_OCR_MODEL_CHAIN)
    workers = max(1, int(os.getenv("LLM_OCR_WORKERS", "6") or "6"))
    jpeg_q = int(os.getenv("LLM_OCR_JPEG_QUALITY", "85") or "85")
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(os.getenv("LLM_OCR_TIMEOUT", "120") or "120"),
    )
    logger.info(f"[OCR-LLM] 模型链 {models}，并发 {workers}，共 {len(images)} 页，JPEG q={jpeg_q}")

    def _one(idx_img):
        idx, img = idx_img
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=jpeg_q)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        for model in models:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    max_tokens=4096,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _LLM_OCR_PROMPT},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        ],
                    }],
                )
                text = (resp.choices[0].message.content or "").strip()
                if text:
                    logger.info(f"[OCR-LLM] 第{idx + 1}页 ← 模型 {model} 识别成功（{len(text)} 字）")
                    return idx, text
            except Exception as e:
                logger.warning(f"LLM OCR 第{idx + 1}页 模型 {model} 失败: {type(e).__name__}: {str(e)[:200]}")
        return idx, ""

    results: list = [""] * len(images)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for idx, text in pool.map(_one, enumerate(images)):
            results[idx] = text
    ok_pages = sum(1 for t in results if t.strip())
    logger.info(f"[OCR-LLM] 完成 {ok_pages}/{len(images)} 页，耗时 {time.time() - t0:.1f}s")
    return results


def _ocr_pages_via_tesseract(images: list, indices) -> list:
    """本地 Tesseract OCR（原实现，作为 LLM 失败时的离线兜底）。"""
    indices = list(indices)
    logger.info(f"[OCR-Tesseract] 本地引擎识别 {len(indices)} 页（lang=chi_sim）")
    try:
        import pytesseract
        import shutil

        tesseract_cmd = shutil.which("tesseract")
        if not tesseract_cmd:
            for candidate in [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"/usr/bin/tesseract",
                r"/usr/local/bin/tesseract",
            ]:
                if Path(candidate).exists():
                    tesseract_cmd = candidate
                    break
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

        out = []
        for i in indices:
            try:
                out.append(pytesseract.image_to_string(images[i], lang="chi_sim", config="--psm 6"))
            except Exception as e:
                logger.error(f"Tesseract 第{i + 1}页失败: {e}")
                out.append("")
        return out
    except Exception as e:
        logger.error(f"Tesseract 不可用: {e}")
        return [""] * len(indices)


def extract_project_name(text: str) -> str:
    explicit = extract_first(text, [
        r"项目名称[:：\s]*([^\n\r，,。；;]{2,50})",
        r"保洁区域[:：\s]*([^\n\r，,。；;]{2,50})",
        r"服务项目[:：\s]*([^\n\r，,。；;]{2,50})",
        r"项目(?!(?:名称|编号|周期|性质|属性|概况|简介|负责|经理|总监|地址|地点|位置|类型|内容|说明|范围|概述|代码|类别|分类|管理|主管|所在))[:：\s]+([^\n\r，,。；;]{2,50})",
    ])
    # OCR 噪声过滤：截到"…以外的其他保"这类断句碎片时视为无效，走兜底关键词
    if explicit and not re.search(r"以外的|其他保|等内容|等相关", explicit):
        return cleanup_project_name(explicit)
    match = re.search(
        r"([\u4e00-\u9fa5A-Za-z0-9（）()·\-]{2,40}(?:项目|广场|中心|大厦|园区|小区|天地|综合体))", text
    )
    return cleanup_project_name(match.group(1)) if match else ""


def cleanup_project_name(value: str) -> str:
    text = str(value or "").strip()
    suffix_match = re.search(
        r"^(.*(?:项目|广场|中心|大厦|园区|小区|天地|综合体|购物广场|商业街))", text
    )
    if suffix_match:
        return suffix_match.group(1).strip(" -_（）()")[:50]
    text = re.sub(
        r"(?:保洁|保安)?(?:外包)?(?:服务|管理)?(?:合同|协议|细则|规则|办法|标准|条款).*$", "", text
    )
    return text.strip(" -_（）()")[:50]


def extract_business_type(text: str) -> str:
    """不再从合同文本中解析业态，改为用户手动从项目-业态映射中选择。"""
    return ""


def extract_first(text: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def extract_supplier(text: str) -> str:
    """读『第一页乙方后字段』作为供应商（用户要求简化口径）。

    流程：
    1. 仅在第一页（\f 之前）文本内匹配，避免合同正文里多次出现的"乙方"行污染
    2. 匹配到 "乙方/供应商/承包方/服务单位/乙方名称" 后的字段
    3. 优先取含公司后缀的字段；只有"全是噪声且无公司名"的行才跳过
    4. 去掉全角/半角括号里的括注（如"（盖xxx章）"），再截断到公司后缀白名单中的第一个
    """
    company_suffixes = [
        "有限公司", "股份公司", "有限责任公司",
        "集团", "实业",
        "服务公司", "环境公司", "清洁公司",
        "物业服务公司", "物业服务部", "保洁服务部",
    ]
    noise_keywords = [
        "盖章", "地址", "地 址", "联系人", "电话", "开户行", "法定代表",
        "授权代表", "邮编", "邮箱", "传真", "日期", "签名", "签字",
    ]
    first_page = text.split("\f", 1)[0] if "\f" in text else text
    patterns = [
        r"(?:乙方|供应商|承包方|服务单位|乙方名称)[:：\s]*([^\n\r，,。；;]{2,60})",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, first_page):
            candidate = match.group(1).strip()
            # 去掉全角/半角括号里的括注（如"（盖xxx章）"、"（签字）"），再去掉残留首部标点
            candidate = re.sub(r"[（(][^）)]*[）)]", "", candidate).strip(" ：:—-、，,。")
            has_company = any(suffix in candidate for suffix in company_suffixes)
            has_noise = any(kw in candidate for kw in noise_keywords)
            # 有公司名 → 直接走截断流程；无公司名但有噪声 → 跳过；无公司名也无噪声 → 走截断
            if not has_company and has_noise:
                continue
            for suffix in company_suffixes:
                if suffix in candidate:
                    idx = candidate.index(suffix) + len(suffix)
                    candidate = candidate[:idx]
                    if 4 <= len(candidate) <= 40:
                        return candidate
                    break
            # 没匹配到公司后缀但也没噪声 → 不返回（candidate 不是公司名）
    return ""


def normalize_date_text(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", "", text)
    text = (
        text.replace("年", "-")
        .replace("月", "-")
        .replace("日", "")
        .replace("/", "-")
        .replace(".", "-")
    )
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return ""
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def extract_contract_rules(text: str) -> dict:
    normalized = normalize_rule_text(text)
    rules = {}

    tier_30_60 = re.search(
        r"迟到或早退30分[钟铁种]以内(?:[（(]包括30分钟?[）)》。]?)?"
        r"扣除(?:标准|标淮)[为:：,，]*(\d+(?:\.\d+)?)元/[次汀江]"
        r".{0,10}?迟到或早退[!1一]小时以内(?:[（(]包括[!1一]?小时?[）)》。]?)?"
        r"扣除(?:标准|标淮)[为:：,，]*(\d+(?:\.\d+)?)元/[次汀江]"
        r".{0,50}?超过[^。；;]{0,30}?1小时按缺勤处理",
        normalized,
    )
    if tier_30_60:
        rules["late_early_tiers"] = [
            {"max_minutes": 30, "amount": float(tier_30_60.group(1))},
            {"max_minutes": 60, "amount": float(tier_30_60.group(2))},
        ]
        rules["late_early_over_minutes_as_absence"] = 60
    else:
        tier_30_only = re.search(
            r"迟到或早退(?:30分[钟铁种]|半小[时])以内(?:[（(]包括(?:30分[钟铁种]?|半小[时]?)[）)》。]?)?"
            r"扣除(?:标准|标淮)[为:：,，E]{0,3}(\d+(?:\.\d+)?)\s*元/[次汀江]"
            r".{0,60}?超过[^。；;]{0,30}?(?:半小[时]|30分[钟铁种])按缺勤处理",
            normalized,
        )
        if tier_30_only:
            rules["late_early_tiers"] = [
                {"max_minutes": 30, "amount": float(tier_30_only.group(1))},
            ]
            rules["late_early_over_minutes_as_absence"] = 30
        else:
            fuzzy_tier = fuzzy_extract_late_early_tier(normalized)
            if fuzzy_tier:
                rules["late_early_tiers"] = fuzzy_tier["tiers"]
                rules["late_early_over_minutes_as_absence"] = fuzzy_tier["over_minutes"]
            else:
                # 小时分档兜底：1小时以内50元、2小时以内100元、超过2小时按缺岗
                hour_tier = extract_hour_late_early_tiers(normalized)
                if hour_tier:
                    rules["late_early_tiers"] = hour_tier["tiers"]
                    rules["late_early_over_minutes_as_absence"] = hour_tier["over_minutes"]

    late = re.search(
        r"迟到[^。；;\n\r]{0,80}?(?:每(?:分钟|分)|按分钟|/分钟|每分钟扣)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*元",
        normalized,
    )
    if late:
        rules["late_deduction_per_minute"] = late.group(1)
    early = re.search(
        r"早退[^。；;\n\r]{0,80}?(?:每(?:分钟|分)|按分钟|/分钟|每分钟扣)[^0-9]{0,12}(\d+(?:\.\d+)?)\s*元",
        normalized,
    )
    if early:
        rules["early_leave_deduction_per_minute"] = early.group(1)

    missing_free = re.search(
        r"每人每月累计(?:漏打卡|未打卡|缺卡)次数超过\s*([一二两三四五六\d]+)\s*次[，,]?\s*扣除标准[为:：,，]*\s*(\d+(?:\.\d+)?)\s*元/人次",
        normalized,
    )
    if missing_free:
        free_times = _cn_or_digit_int(missing_free.group(1))
        if free_times:
            rules["missing_clock_free_times_per_month"] = float(free_times)
        rules["missing_clock_deduction"] = missing_free.group(2)
    if "missing_clock_deduction" not in rules:
        fuzzy_missing = fuzzy_extract_missing_clock_deduction(normalized)
        if fuzzy_missing:
            rules["missing_clock_deduction"] = fuzzy_missing
    if "missing_clock_free_times_per_month" not in rules:
        free_match = re.search(
            r"(?:前|超过)\s*([一二两三四五六\d]+)\s*次[^。；;]{0,30}?(?:不扣款|免扣|需提供出勤证明)", normalized
        )
        if free_match:
            free_times = _cn_or_digit_int(free_match.group(1))
            if free_times:
                rules["missing_clock_free_times_per_month"] = float(free_times)
    if "missing_clock_free_times_per_month" not in rules:
        # "三次以内不做扣款" / "3次以内不扣款" 这类倒叙写法
        free_match = re.search(
            r"([一二两三四五六\d]+)\s*次以内[^。；;]{0,20}?(?:不做?扣款|免扣)", normalized
        )
        if free_match:
            free_times = _cn_or_digit_int(free_match.group(1))
            if free_times:
                rules["missing_clock_free_times_per_month"] = float(free_times)
    proof_required = re.search(
        r"(?:在提供有效出勤证明的前提下|有出勤(?:凭证|证明|证)的情况下)[^。；;]{0,40}(?:三次以内|两次以内|前\d+次|月度\d+次内)[^。；;]{0,20}不做扣款",
        normalized,
    )
    if proof_required:
        rules["missing_clock_free_requires_attendance_proof"] = True
    if "missing_clock_free_requires_attendance_proof" not in rules:
        if "漏打卡" in normalized and "出勤证明" in normalized:
            rules["missing_clock_free_requires_attendance_proof"] = True

    cap = re.search(
        r"(?:单人单日|每日|日)[^。；;\n\r]{0,40}?上限[^0-9]{0,10}(\d+(?:\.\d+)?)\s*元", normalized
    )
    if cap:
        rules["single_person_daily_cap"] = cap.group(1)

    rules["contract_deduction_coefficient"] = extract_shortage_coefficient(normalized)

    clock_count = None
    if re.search(r"早[、，,]?\s*中[、，,]?\s*晚[^。；;\n\r]{0,20}?三\s*次", normalized) or \
       re.search(r"不少于[^。；;\n\r]{0,20}?三\s*次[^。；;\n\r]{0,10}?打卡", normalized) or \
       re.search(r"三\s*次[^。；;\n\r]{0,10}?早[、，,]?\s*中[、，,]?\s*晚", normalized):
        clock_count = 3
    if clock_count is None:
        m = re.search(r"(?:每日|每天|日常)[^。；;\n\r]{0,15}?(?:打卡|考勤|打卡记录)\s*(\d+)\s*次", normalized)
        if m:
            clock_count = int(m.group(1))
    if clock_count is None:
        m = re.search(r"(?:每日|每天|日常)[^。；;\n\r]{0,15}?(?:打卡|考勤)\s*([二两三四五六])\s*次", normalized)
        if m and m.group(1) in {"一", "两", "二", "三", "四", "五", "六"}:
            clock_count = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}[m.group(1)]
    if clock_count is None:
        m = re.search(r"(?:上班|每日|每天)[^。；;\n\r]{0,10}?(?:需|要求|应当|应该|必须)[^。；;\n\r]{0,10}?([二两三四五六])\s*次(?:卡|打卡)", normalized)
        if m and m.group(1) in {"一", "两", "二", "三", "四", "五", "六"}:
            clock_count = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6}[m.group(1)]
    if clock_count is not None:
        rules["required_clock_count"] = clock_count

    return rules


def fuzzy_extract_late_early_tier(normalized: str) -> dict | None:
    keyword_positions = [m.start() for m in re.finditer(r"迟到或早退|迟到", normalized)]
    if not keyword_positions:
        return None

    tiers = []
    over_minutes = None

    for pos in keyword_positions:
        context = normalized[pos:pos + 200]
        match_30 = re.search(
            r"(?:30分[钟铁种]|半小[时]).{0,20}?扣除.{0,5}?(\d+(?:\.\d+)?)\s*元/[次汀江]", context
        )
        if match_30:
            amount = float(match_30.group(1))
            if not any(t["max_minutes"] == 30 for t in tiers):
                tiers.append({"max_minutes": 30, "amount": amount})
        match_60 = re.search(
            r"(?:[!1一]小时|60分[钟铁种]).{0,20}?扣除.{0,5}?(\d+(?:\.\d+)?)\s*元/[次汀江]", context
        )
        if match_60:
            amount = float(match_60.group(1))
            if not any(t["max_minutes"] == 60 for t in tiers):
                tiers.append({"max_minutes": 60, "amount": amount})
        match_over = re.search(r"超过.{0,10}?(?:[!1一]小时|半小[时]|30分[钟铁种]).{0,10}?按缺勤", context)
        if match_over:
            if "1小时" in match_over.group(0) or "一小时" in match_over.group(0):
                over_minutes = 60
            elif "半小" in match_over.group(0) or "30分" in match_over.group(0):
                over_minutes = 30

    if not tiers:
        return None
    if over_minutes is None:
        over_minutes = 60 if any(t["max_minutes"] == 60 for t in tiers) else 30
    return {"tiers": tiers, "over_minutes": over_minutes}


def fuzzy_extract_missing_clock_deduction(normalized: str) -> str | None:
    for m in re.finditer(r"漏打卡|未打卡|缺卡", normalized):
        pos = m.start()
        context = normalized[pos:pos + 100]
        match = re.search(r"(\d+(?:\.\d+)?)\s*元(?:/人次)?", context)
        if match:
            return match.group(1)
    return None


def _cn_or_digit_int(value: str) -> int | None:
    """中文数字/阿拉伯数字转 int（OCR 里"3次"和"三次"都常见）。"""
    value = str(value or "").strip()
    if not value:
        return None
    cn = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in cn:
        return cn[value]
    m = re.search(r"\d+", value)
    return int(m.group(0)) if m else None


def extract_hour_late_early_tiers(normalized: str) -> dict | None:
    """按『小时』分档的迟到/早退扣款提取（分钟档提取失败后的兜底）。

    典型原文：迟到或早退1小时以内50元/人次、迟到或早退2小时以内100元/人次、超过2小时按缺岗处理
    返回 {"tiers": [{max_minutes, amount}, ...], "over_minutes": int} 或 None。
    """
    tiers: list[dict] = []
    for m in re.finditer(
        r"迟到或早退\s*([!1一二两三四五六\d]+)\s*小[时吋]\s*以内[^0-9]{0,6}?"
        r"(\d+(?:\.\d+)?)\s*元/[次人次]{1,2}",
        normalized,
    ):
        hours = _cn_or_digit_int(m.group(1))
        if not hours:
            continue
        minutes = hours * 60
        if not any(t["max_minutes"] == minutes for t in tiers):
            tiers.append({"max_minutes": minutes, "amount": float(m.group(2))})
    if not tiers:
        return None

    tiers.sort(key=lambda t: t["max_minutes"])
    over_minutes = None
    m = re.search(
        r"超过\s*([!1一二两三四五六\d]+)\s*小[时吋][^。；;]{0,6}?按?缺[勤岗]",
        normalized,
    )
    if m:
        hours = _cn_or_digit_int(m.group(1))
        if hours:
            over_minutes = hours * 60
    if over_minutes is None:
        over_minutes = max(t["max_minutes"] for t in tiers)
    return {"tiers": tiers, "over_minutes": over_minutes}


def extract_shortage_coefficient(normalized: str) -> str | None:
    for m in re.finditer(r"工时单价([^。；;]{0,30}?)(?:缺勤|铁勤)总时长", normalized):
        middle = m.group(1)
        middle_clean = re.sub(r'(\d)4$', r'\1', middle)
        middle_clean = re.sub(r'^4(\d)', r'\1', middle_clean)

        match = re.search(r"[\*#]?\s*(\d+[.,，。]\d+)\s*[\*#]?", middle_clean)
        if match:
            val = match.group(1).replace(",", ".").replace("，", ".").replace("。", ".")
            return val
        match = re.search(r"[\*#](1\d{1,2})(?!\d)", middle_clean)
        if match:
            val = match.group(1)
            return f"{val[0]}.{val[1:]}"
        match = re.search(r"[\*#]?\s*(\d)\s*[\*#]?", middle_clean)
        if match:
            return match.group(1)
    return None


def normalize_rule_text(text: str) -> str:
    value = str(text or "")
    value = re.sub(r"\s+", "", value)

    replacements = {
        "O": "0", "o": "0", "￥": "元", "／": "/", "—": "-", "－": "-",
        "每分种": "每分钟", "迟倒": "迟到", "旱退": "早退",
        "分铁": "分钟", "包揪": "包括", "扒除": "扣除", "抚除": "扣除",
        "速约": "违约", "银岗": "缺岗", "铁勤": "缺勤", "标淮": "标准",
        "早逾": "早退", "溥打卡": "漏打卡", "漪打卡": "漏打卡",
        "汀": "次", "江": "次", "逾": "退",
        "武早逆": "或早退", "早迹": "早退", "早追": "早退",
        "扣院": "扣除", "扣院标准": "扣除标准",
        "不敏)": "不做", "不敏）": "不做",
        "湘打卡": "漏打卡", "漾打卡": "漏打卡",
        "缺门": "缺岗", "跌勤": "缺勤", "狒勤": "缺勤",
        "工时单价#": "工时单价*", "单价#": "单价*",
        "单价*019": "单价*0.1*9", "单价*0.1*9在岗": "单价*1在岗",
        "湖打卡": "漏打卡", "渑打卡": "漏打卡", "湾打卡": "漏打卡",
        "缺勇总时长": "缺勤总时长", "缺勒总时长": "缺勤总时长",
        "包拾": "包括", "包芸": "包括",
        "元7欣": "元/次", "元/欣": "元/次",
        "早迟": "早退", "早迫": "早退",
        "迟则": "迟到", "扣陈": "扣除",
        "扬款": "扣款", "扣院标准为": "扣除标准为",
        "魅过": "超过", "技缺": "按缺",
        "缺勒处理": "缺勤处理", "缺勤处理": "缺勤处理",
        "丁做": "不做", "祝荣": "累计",
        "计渑": "计漏",
        "缺勤盐时长": "缺勤总时长", "缺盐时长": "缺勤总时长",
        "铧勤": "缺勤", "铧岗": "缺岗",
        "挂铧勤处理": "按缺勤处理",
        "返到": "迟到", "早遏": "早退",
        "分钝": "分钟",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r'包[^括]{0,5}括', '包括', value)
    value = value.replace("超过!小时", "超过1小时").replace("超过!小", "超过1小")
    value = re.sub(r'迟到[武或戊戌则]早[逆退迹追逾迟迫]', '迟到或早退', value)
    value = re.sub(r'[壕濠豪]到或早[进退迹]', '迟到或早退', value)
    value = re.sub(r'[遅迗]到或早退', '迟到或早退', value)
    value = re.sub(r'超过\s*!\s*小时', '超过1小时', value)
    value = re.sub(r'[按接技]缺[岗勤]处理', lambda m: '按缺勤处理' if m.group(0).endswith('勤') else '按缺岗处理', value)
    value = re.sub(r'扣[院陈降险]标准', '扣除标准', value)
    value = re.sub(r'[湘漾溥漪湖渑湾]打卡', '漏打卡', value)
    value = re.sub(r'[跌狒铁勇]勤', '缺勤', value)
    value = re.sub(r'(?:缺)?[勇勒盐]总时长', '缺勤总时长', value)
    value = re.sub(r'[铧铁跌狒]勤', '缺勤', value)
    value = re.sub(r'[铧银]岗', '缺岗', value)
    value = re.sub(r'挂[铧铁]?勤处理', '按缺勤处理', value)
    value = value.replace("返到", "迟到").replace("早遏", "早退")
    value = value.replace("分钝", "分钟")
    value = value.replace("银岗", "缺岗")
    value = re.sub(r'扣[陈院降险]标准为', '扣除标准为', value)
    value = value.replace("丁做", "不做")
    value = value.replace("扬款", "扣款")
    value = re.sub(r'元[7/]欣', '元/次', value)
    value = value.replace("魅过", "超过")
    value = value.replace("技缺勒处理", "按缺勤处理").replace("技缺勤处理", "按缺勤处理")

    return value
