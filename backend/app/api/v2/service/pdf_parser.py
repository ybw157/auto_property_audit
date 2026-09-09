"""PDF 合同解析器 —— 从 PDF 中提取文本并解析结构化扣款细则。

移植自 GitHub 版本的 regex + OCR 解析方案，不依赖 LLM API。
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_contract_metadata(path: Path, original_name: str) -> dict:
    text = extract_contract_text(Path(path))
    source = f"{Path(original_name).stem}\n{text}"
    # 合同有效期：按用户口径只读『合同期限』这一行（不再依赖"自/从/起"前缀）
    start_date, end_date = extract_contract_period(source)
    return {
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


def extract_contract_period(text: str) -> tuple[str, str]:
    """读『合同期限』这一行的两个日期（用户要求简化口径，不再依赖"自/从/起"前缀）。

    匹配优先级：
    1. 找第一行形如『合同期限：xxxx 至 xxxx』的内容
    2. 从该行内提取两个 YYYY-MM-DD 形式日期
    """
    m = re.search(r"合同期限[:：\s]*([^\n\r]{2,120})", text)
    if not m:
        return "", ""
    line = m.group(1)
    dates = re.findall(r"\d{4}[年/\-.]\d{1,2}[月/\-.]\d{1,2}", line)
    if len(dates) >= 2:
        return normalize_date_text(dates[0]), normalize_date_text(dates[1])
    return "", ""


def extract_contract_text(path: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        # 用 \f（form feed）分隔每页，extract_supplier 借此只读第一页乙方字段
        text = "\f".join(page.extract_text() or "" for page in reader.pages)
        stripped = text.strip()
        meaningful_chars = len(
            stripped.replace("契约锁", "").replace(" ", "").replace("\n", "").replace("\r", "").replace("\f", "")
        )
        if len(stripped) < 200 or meaningful_chars < 100:
            text = ocr_pdf_text(path)
        return text
    except Exception as e:
        logger.warning(f"PDF 文本提取失败，尝试 OCR: {e}")
        return ocr_pdf_text(path)


def ocr_pdf_text(path: Path) -> str:
    try:
        import pypdfium2 as pdfium
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

        pdf = pdfium.PdfDocument(str(path))
        texts = []
        for index in range(len(pdf)):
            page = pdf[index]
            image = page.render(scale=2.0).to_pil()
            texts.append(pytesseract.image_to_string(image, lang="chi_sim", config="--psm 6"))
        return "\n".join(texts)
    except Exception as e:
        logger.error(f"OCR 解析失败: {e}")
        return ""


def extract_project_name(text: str) -> str:
    explicit = extract_first(text, [
        r"项目名称[:：\s]*([^\n\r，,。；;]{2,50})",
        r"保洁区域[:：\s]*([^\n\r，,。；;]{2,50})",
        r"服务项目[:：\s]*([^\n\r，,。；;]{2,50})",
        r"项目(?!(?:名称|编号|周期|性质|属性|概况|简介|负责|经理|总监|地址|地点|位置|类型|内容|说明|范围|概述|代码|类别|分类|管理|主管|所在))[:：\s]+([^\n\r，,。；;]{2,50})",
    ])
    if explicit:
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
    value = extract_first(text, [
        r"(?:项目属性|业态|业务类型)[:：\s]*([^\n\r，,。；;]{1,12})",
    ])
    return normalize_business_type_label(value)


def normalize_business_type_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "商酒" in text:
        return "商业"
    if text in {"商", "商场"} or "商业" in text:
        return "商业"
    if text == "住" or "住宅" in text:
        return "住宅"
    if "写字楼" in text or "办公" in text:
        return "写字楼"
    if "酒店" in text:
        return "酒店"
    if "街区" in text or "外场" in text:
        return "街区"
    return text


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
        r"每人每月累计(?:漏打卡|未打卡|缺卡)次数超过(\d+)次,?扣除标准[为:：,，]*(\d+(?:\.\d+)?)元/人次",
        normalized,
    )
    if missing_free:
        rules["missing_clock_free_times_per_month"] = float(missing_free.group(1))
        rules["missing_clock_deduction"] = missing_free.group(2)
    if "missing_clock_deduction" not in rules:
        fuzzy_missing = fuzzy_extract_missing_clock_deduction(normalized)
        if fuzzy_missing:
            rules["missing_clock_deduction"] = fuzzy_missing
    if "missing_clock_free_times_per_month" not in rules:
        free_match = re.search(
            r"(?:前|超过)(\d+)次[^。；;]{0,30}?(?:不扣款|免扣|需提供出勤证明)", normalized
        )
        if free_match:
            rules["missing_clock_free_times_per_month"] = float(free_match.group(1))
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
