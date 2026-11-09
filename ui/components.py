"""여러 화면에서 함께 쓰는 표시 도우미.

사용자가 입력한 값은 HTML로 그리지 않는다.
마크다운 문장 안에 넣을 때는 `md_escape`로 특수 문자를 무력화한다.
"""
from __future__ import annotations

import re

import streamlit as st

from src.config import RULE_NAMES

# 상태 코드 → (화면 문구, 배지 색). 색만으로 구분하지 않도록 항상 문구를 함께 쓴다.
STATUS_INFO: dict[str, tuple[str, str]] = {
    "processing": ("처리 중", "gray"),
    "pending_review": ("승인 대기", "orange"),
    "auto_published": ("자동 등록", "green"),
    "approved_published": ("승인 후 등록", "green"),
    "rejected": ("반려", "red"),
    "failed": ("처리 실패", "red"),
}

# 승인 담당자 응답 코드 → 화면 문구
ACTION_LABELS: dict[str, str] = {
    "approve": "승인",
    "approve_with_edits": "수정 후 승인",
    "reject": "반려",
    "reassess": "다시 판정",
}

# 처리 이력에 남는 사건 코드 → 화면 문구 (모르는 코드는 그대로 보여 준다)
EVENT_LABELS: dict[str, str] = {
    "submitted": "등록 요청 접수",
    "generated": "콘텐츠 생성",
    "generation_failed": "콘텐츠 생성 실패",
    "validated": "자동 검증",
    "review_requested": "승인 대기함으로 이동",
    "review_invalid": "응답 반영 안 됨",
    "approved": "승인",
    "edited": "담당자 수정 반영",
    "reassess_requested": "다시 판정 요청",
    "regenerated": "콘텐츠 다시 생성",
    "published": "데모 카탈로그 등록",
    "rejected": "반려",
    "failed": "처리 실패",
}

# 처리 이력의 처리자 코드 → 화면 문구
ACTOR_LABELS: dict[str, str] = {"human": "담당자", "system": "시스템"}

# 마지막 처리 코드 → 화면 문구 ("auto"는 자동 등록)
LAST_ACTION_LABELS: dict[str, str] = {"auto": "자동 등록", **ACTION_LABELS}

# 데모 카탈로그 등록 방식 → 화면 문구
PUBLICATION_LABELS: dict[str, str] = {
    "auto": "자동 등록",
    "auto_published": "자동 등록",
    "human": "사람 승인",
    "approved_published": "사람 승인",
}

GENERATION_MODE_LABELS: dict[str, str] = {
    "sample": "샘플 모드",
    "ollama": "Ollama (로컬 LLM)",
}

# 원본 상품 정보 필드 → 화면 문구
PRODUCT_FIELD_LABELS: dict[str, str] = {
    "product_id": "상품 ID",
    "product_name": "상품명",
    "category": "카테고리",
    "material": "소재",
    "colors": "색상",
    "sizes": "사이즈",
    "selling_price": "정상 판매가",
    "sale_price": "할인가",
    "care_instructions": "관리 방법",
    "approved_claims": "입증된 기능 표현",
    "source_notes": "참고 자료",
}

# 생성 콘텐츠 필드 → 화면 문구
CONTENT_FIELD_LABELS: dict[str, str] = {
    "display_title": "상품 제목",
    "one_line_summary": "한 줄 요약",
    "selling_points": "핵심 장점",
    "detail_description": "상세 설명",
    "care_guide": "관리 안내",
    "seo_keywords": "검색 키워드",
    "hashtags": "해시태그",
    "price_display": "가격 표시",
}

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~:$])")


REVIEW_STYLES = """
<style>
.stApp .st-key-review_workspace { min-width: 0; gap: 12px; }
.st-key-review_workspace .st-key-review_response,
.st-key-review_workspace [class*="st-key-pending_card_"] { gap: 12px; }
.st-key-review_response h4 { padding: 0 0 8px; }
.st-key-review_workspace [data-testid="stColumn"],
.st-key-review_workspace [data-testid="stVerticalBlock"],
.st-key-review_workspace [data-testid="stMarkdownContainer"] {
    min-width: 0;
    max-width: 100%;
}
.st-key-review_workspace [data-testid="stText"],
.st-key-review_workspace [data-testid="stMarkdownContainer"] p,
.st-key-review_workspace [data-testid="stMarkdownContainer"] li,
.st-key-review_workspace h3,
.st-key-review_workspace h4 {
    overflow-wrap: anywhere;
    word-break: normal;
}
.st-key-review_workspace [data-testid="stText"] {
    white-space: pre-wrap;
    line-height: 1.65;
}
.st-key-review_workspace [data-testid="stButton"] button {
    min-height: 44px;
    height: auto;
    padding: 10px 14px;
}
.st-key-review_workspace [data-testid="stButton"] button p,
.st-key-review_workspace [data-testid="stWidgetLabel"] p,
.st-key-review_workspace [role="radio"] + div p {
    white-space: normal;
    overflow-wrap: anywhere;
    line-height: 1.45;
}
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> .st-key-review_response),
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> .st-key-pending_filters),
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> .st-key-review_original),
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> .st-key-review_generated),
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> [class*="st-key-review_evidence_"]),
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> [class*="st-key-pending_card_"]) {
    background: #FFFFFF;
    border-color: #E3E1E4;
    border-radius: 5px;
}
.st-key-review_workspace [data-testid="stLayoutWrapper"]:has(> .st-key-review_response) { background: #F9F6FF; }
.st-key-review_response [role="radiogroup"] {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
}
.st-key-review_response [role="radiogroup"] label {
    min-width: 0;
    margin: 0;
    padding: 9px 8px;
    border: 1px solid #E3E1E4;
    border-radius: 10px;
}
.st-key-review_response [role="radiogroup"] label:has(input:checked),
.st-key-review_response [role="radiogroup"] label:has([aria-checked="true"]) {
    background: #EFEDF6;
    border-color: #656A83;
}
.st-key-review_response [role="radiogroup"] label:focus-within {
    outline: 2px solid #656A83;
    outline-offset: 2px;
}
@media (max-width: 960px) {
    :is(.st-key-review_decision_grid, .st-key-review_source_grid, .st-key-pending_filters, .st-key-review_toolbar)
    > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
        flex-direction: column;
        align-items: stretch;
    }
    :is(.st-key-review_decision_grid, .st-key-review_source_grid, .st-key-pending_filters, .st-key-review_toolbar)
    > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
        width: 100%;
        flex: 1 1 100%;
    }
}
@media (max-width: 640px) {
    .st-key-review_workspace [data-testid="stHorizontalBlock"] {
        flex-direction: column;
        align-items: stretch;
    }
    .st-key-review_workspace [data-testid="stColumn"] {
        width: 100%;
        flex: 1 1 100%;
    }
}
</style>
"""


def review_styles() -> None:
    """승인 화면의 고정 스타일만 삽입한다."""
    st.markdown(REVIEW_STYLES, unsafe_allow_html=True)


def show_product(product: dict | None) -> None:
    """원본 값을 생략하거나 가로로 스크롤하지 않고 보여 준다."""
    for row in product_rows(product):
        st.markdown(f"**{row['항목']}**")
        st.text(row["값"], width="stretch")


def show_review_flags(flags: list[dict] | None) -> None:
    """기준별로 원본·생성값과 근거 전체를 줄바꿈해서 대조한다."""
    if not flags:
        st.caption("검증에서 발견된 문제가 없습니다.")
        return
    for index, row in enumerate(flag_rows(flags)):
        with st.container(border=True, key=f"review_evidence_{index}"):
            st.markdown(f"**{md_escape(row['기준'])}**")
            st.caption(f"항목: {md_escape(row['항목'])}")
            source, generated = st.columns(2, gap="medium")
            with source:
                st.markdown("**원본 값**")
                st.text(row["원본 값"], width="stretch")
            with generated:
                st.markdown("**AI가 쓴 값**")
                st.text(row["AI가 쓴 값"], width="stretch")
            st.markdown("**근거 문장**")
            st.text(row["근거 문장"], width="stretch")


def md_escape(text: object) -> str:
    """마크다운 특수 문자를 무력화해 사용자 입력이 서식·링크로 바뀌지 않게 한다."""
    return _MD_SPECIAL.sub(r"\\\1", str(text if text is not None else ""))


def status_label(status: str | None) -> str:
    """상태 코드를 한국어 문구로 바꾼다."""
    return STATUS_INFO.get(status or "", (status or "알 수 없음", "gray"))[0]


def status_badge(status: str | None) -> None:
    """상태를 색과 문구가 함께 있는 배지로 보여 준다."""
    label, color = STATUS_INFO.get(status or "", (status or "알 수 없음", "gray"))
    st.badge(label, color=color)


def overdue_badge() -> None:
    """승인 대기가 오래된 요청에 붙이는 지연 배지."""
    st.badge("지연", icon=":material/schedule:", color="red")


def rule_label(rule: str) -> str:
    """기준 글자에 기준 이름을 붙인다. 예: 'B · 근거 없는 기능·효능·인증 표현'"""
    return f"{rule} · {RULE_NAMES.get(rule, '알 수 없는 기준')}"


def rules_hit(flags: list[dict] | None) -> list[str]:
    """걸린 기준 글자를 중복 없이 순서대로 돌려준다."""
    seen: list[str] = []
    for flag in flags or []:
        rule = str(flag.get("rule", ""))
        if rule and rule not in seen:
            seen.append(rule)
    return seen


def rules_text(flags: list[dict] | None) -> str:
    """걸린 기준을 한 줄 문구로 만든다."""
    rules = rules_hit(flags)
    return ", ".join(rule_label(r) for r in rules) if rules else "없음"


def warning_summary(flags: list[dict] | None) -> str:
    """경고 요약: 첫 경고 문구와 나머지 건수."""
    flags = flags or []
    if not flags:
        return "경고 없음"
    first = review_message(flags[0].get("message", ""))
    return first if len(flags) == 1 else f"{first} 외 {len(flags) - 1}건"


def review_message(message: object) -> str:
    """검증 문장 속 필드 식별자를 화면용 한국어 이름으로 바꾼다."""
    text = str(message or "")
    labels = {**PRODUCT_FIELD_LABELS, **CONTENT_FIELD_LABELS}
    for field in sorted(labels, key=len, reverse=True):
        text = text.replace(field, labels[field])
    return text


def join_value(value: object) -> str:
    """목록·숫자·빈 값을 사람이 읽기 좋은 문자열로 바꾼다."""
    if value is None or value == "" or value == []:
        return "(비어 있음)"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int):
        return f"{value:,}원" if value >= 1000 else str(value)
    return str(value)


def format_time(value: str | None) -> str:
    """ISO 시각 문자열을 'YYYY-MM-DD HH:MM'으로 줄인다."""
    if not value:
        return "-"
    text = str(value).replace("T", " ")
    return text[:16]


def product_rows(product: dict | None) -> list[dict]:
    """원본 상품 정보를 '항목 / 값' 표의 행으로 바꾼다."""
    product = product or {}
    rows = []
    for key, label in PRODUCT_FIELD_LABELS.items():
        rows.append({"항목": label, "값": join_value(product.get(key))})
    return rows


def flag_rows(flags: list[dict] | None) -> list[dict]:
    """검증 경고를 '원본 값 vs AI가 쓴 값' 비교 표의 행으로 바꾼다."""
    rows = []
    for flag in flags or []:
        field = str(flag.get("field", ""))
        rows.append(
            {
                "기준": rule_label(str(flag.get("rule", ""))),
                "항목": PRODUCT_FIELD_LABELS.get(field) or CONTENT_FIELD_LABELS.get(field) or field or "-",
                "원본 값": flag.get("source_value") or "(원본에 없음)",
                "AI가 쓴 값": flag.get("generated_value") or "-",
                "근거 문장": flag.get("evidence") or "-",
            }
        )
    return rows


def show_table(rows: list[dict], *, empty_text: str = "표시할 내용이 없습니다.") -> None:
    """행 목록을 표로 보여 준다. 표 안의 값은 서식 없이 글자 그대로 나온다."""
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    else:
        st.caption(empty_text)


def show_content(content: dict | None, *, wide: bool = False) -> None:
    """생성 콘텐츠(또는 최종 콘텐츠)를 읽기 좋게 보여 준다. 값은 글자 그대로 출력한다."""
    if not content:
        st.caption("생성된 콘텐츠가 없습니다.")
        return
    if wide:
        _show_wide_content(content)
        return
    st.markdown(f"**{CONTENT_FIELD_LABELS['display_title']}**")
    st.text(content.get("display_title") or "-", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['one_line_summary']}**")
    st.text(content.get("one_line_summary") or "-", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['selling_points']}**")
    for point in content.get("selling_points") or []:
        st.text(f"• {point}", width="stretch")
    if not content.get("selling_points"):
        st.text("(핵심 장점 없음)", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['detail_description']}**")
    st.text(content.get("detail_description") or "-", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['care_guide']}**")
    st.text(content.get("care_guide") or "(관리 안내 없음)", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['price_display']}**")
    st.text(content.get("price_display") or "(가격 표시 없음)", width="stretch")
    keywords = content.get("seo_keywords") or []
    tags = content.get("hashtags") or []
    st.markdown(f"**{CONTENT_FIELD_LABELS['seo_keywords']}**")
    st.text(", ".join(keywords) or "(키워드 없음)", width="stretch")
    st.markdown(f"**{CONTENT_FIELD_LABELS['hashtags']}**")
    st.text(" ".join(tags) or "(해시태그 없음)", width="stretch")
    claims = content.get("fact_claims") or []
    if claims:
        with st.expander(f"사실 주장 목록 ({len(claims)}건)"):
            show_table(
                [
                    {
                        "주장": c.get("claim", ""),
                        "종류": c.get("claim_type", ""),
                        "근거 필드": PRODUCT_FIELD_LABELS.get(c.get("source_field", ""), c.get("source_field", "")) or "-",
                        "근거 값": c.get("source_value") or "-",
                    }
                    for c in claims
                ]
            )


def _show_wide_content(content: dict) -> None:
    """카탈로그의 전체 콘텐츠를 항목명과 값의 넓은 행으로 보여 준다."""
    fields = (
        "display_title", "one_line_summary", "selling_points", "detail_description",
        "care_guide", "price_display", "seo_keywords", "hashtags",
    )
    for field in fields:
        label, value = st.columns([1, 5], gap="medium")
        label.caption(CONTENT_FIELD_LABELS[field])
        data = content.get(field)
        with value:
            if field == "selling_points":
                for point in data or []:
                    st.text(f"• {point}", width="stretch")
                if not data:
                    st.text("(핵심 장점 없음)", width="stretch")
            elif isinstance(data, list):
                separator = " " if field == "hashtags" else ", "
                st.text(separator.join(str(item) for item in data) or "(비어 있음)", width="stretch")
            else:
                st.text(str(data) if data not in (None, "") else "(비어 있음)", width="stretch")
    claims = content.get("fact_claims") or []
    if claims:
        with st.expander(f"사실 주장 목록 ({len(claims)}건)"):
            show_table([
                {
                    "주장": claim.get("claim") or "-",
                    "종류": claim.get("claim_type") or "-",
                    "근거 필드": PRODUCT_FIELD_LABELS.get(claim.get("source_field"), claim.get("source_field")) or "-",
                    "근거 값": join_value(claim.get("source_value")),
                }
                for claim in claims
            ])


def show_events(events: list[dict] | None) -> None:
    """처리 이력 타임라인을 시간 순서대로 보여 준다."""
    if not events:
        st.caption("기록된 이력이 없습니다.")
        return
    rows = [
        {
            "시각": format_time(e.get("created_at")),
            "처리": EVENT_LABELS.get(str(e.get("action", "")), str(e.get("action", ""))),
            "처리자": ACTOR_LABELS.get(str(e.get("actor", "")), e.get("actor") or "-"),
            "사유·메모": e.get("reason_or_note") or "-",
        }
        for e in events
    ]
    show_table(rows)
