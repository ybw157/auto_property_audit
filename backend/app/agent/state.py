from typing import TypedDict, Annotated, Optional, Any
from langgraph.graph.message import add_messages

from app.agent.models import ContractRules, DeductionRule, ContractAuditParams, ContractMetadata


class ContractAgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]

    pdf_path: str
    pdf_pages: Optional[list[str]]
    pdf_page_count: int

    ocr_text: Optional[str]
    ocr_pages: Optional[list[dict[str, Any]]]

    raw_rules: Optional[ContractRules]
    validated_rules: Optional[list[DeductionRule]]

    deduction_page_indices: Optional[list[int]]
    audit_params: Optional[ContractAuditParams]

    contract_metadata: Optional[ContractMetadata]

    model_key: str
    error: Optional[str]
