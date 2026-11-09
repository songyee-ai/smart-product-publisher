"""입력·출력·그래프 상태의 형태를 정의한다.

- ProductInput: 담당자가 입력하는 원본 상품 정보
- GeneratedContent: AI가 만든 상세페이지 콘텐츠
- ValidationFlag: 검증에서 발견한 문제 한 건
- ReviewResponse: 승인 담당자의 응답
- PublisherState: LangGraph가 단계마다 저장하는 상태
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, Field, field_validator

ClaimType = Literal["material", "color", "size", "price", "function", "care", "composition", "other"]
ReviewAction = Literal["approve", "approve_with_edits", "reject", "reassess"]
Status = Literal[
    "processing",
    "pending_review",
    "auto_published",
    "approved_published",
    "rejected",
    "failed",
]


class ProductInput(BaseModel):
    """원본 상품 정보. 빈 값은 그대로 둔다(추측해서 채우지 않는다)."""

    product_id: str = Field(min_length=1)
    product_name: str = Field(min_length=1)
    category: str = "침구"
    material: str = ""
    colors: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    selling_price: Optional[int] = None  # 정상 판매가(원)
    sale_price: Optional[int] = None  # 할인가(원), 없으면 None
    care_instructions: str = ""
    approved_claims: list[str] = Field(default_factory=list)  # 근거 자료로 입증된 기능만
    source_notes: str = ""

    @field_validator("colors", "sizes", "approved_claims", mode="before")
    @classmethod
    def _split_text(cls, value):
        # 화면에서 "아이보리, 베이지"처럼 문자열로 들어오면 목록으로 바꾼다.
        if isinstance(value, str):
            return [part.strip() for part in value.replace("\n", ",").split(",") if part.strip()]
        return value


class FactClaim(BaseModel):
    """생성 콘텐츠에 들어간 객관적 사실·기능 주장 한 건."""

    claim: str
    claim_type: ClaimType = "other"
    source_field: str = ""  # 근거가 된 원본 필드 이름 (없으면 빈 문자열)
    source_value: str = ""  # 근거가 된 원본 값


class GeneratedContent(BaseModel):
    """AI가 생성한 상세페이지 콘텐츠."""

    display_title: str = Field(min_length=1)
    one_line_summary: str = Field(min_length=1)
    selling_points: list[str] = Field(min_length=1)
    detail_description: str = Field(min_length=1)
    care_guide: str = ""
    seo_keywords: list[str] = Field(default_factory=list)
    hashtags: list[str] = Field(default_factory=list)
    fact_claims: list[FactClaim] = Field(default_factory=list)
    price_display: Optional[str] = None


class ValidationFlag(TypedDict):
    """검증에서 발견한 문제 한 건. 승인 화면의 '멈춘 이유'와 '검증 근거'가 된다."""

    rule: str  # "A" | "B" | "C" | "D" | "E" | "S"
    code: str  # 예: "material_mismatch", "unsupported_claim"
    message: str  # 사람이 읽는 한국어 설명
    field: str  # 관련 필드 이름 (예: "material")
    source_value: str  # 원본 값 (없으면 "")
    generated_value: str  # AI가 쓴 값 또는 문제 표현
    evidence: str  # 문제가 발견된 문장 일부


class ReviewResponse(TypedDict, total=False):
    """승인 담당자의 응답. Command(resume=...)로 그래프에 들어간다."""

    action: ReviewAction
    edits: dict  # approve_with_edits: {"display_title": ..., "detail_description": ...}
    reason: str  # reject: 반려 사유(필수) / approve: 승인 메모(상한 도달 시 필수)
    instructions: str  # reassess: 다시 작성 지시
    reviewer: str  # 담당자 이름


class PublisherState(TypedDict, total=False):
    """LangGraph 상태. 단계가 끝날 때마다 체크포인터에 저장된다."""

    submission_id: str
    thread_id: str
    product_input: dict
    generation_mode: str  # "sample" | "ollama"
    sample_id: Optional[str]  # 샘플로 실행한 경우 샘플 ID
    injection: Optional[str]  # 데모용 위험 문구 주입 시나리오 ID
    generated_content: Optional[dict]
    validation_flags: list[ValidationFlag]
    validation_passed: bool
    review_required: bool
    review_response: Optional[dict]
    human_edits: Optional[dict]
    reassessment_instructions: Optional[str]
    regeneration_count: int
    edit_round: int
    final_content: Optional[dict]
    processing_route: str  # "auto" | "human"
    status: str
    rejection_reason: Optional[str]
    event_history: list[dict]
    error_message: Optional[str]
