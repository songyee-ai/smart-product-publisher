"""화면 7개(대시보드 ~ 데모 카탈로그)를 그리는 함수 모음.

동작(등록·승인·반려 등)은 모두 `src.service`를 통해서만 실행한다.
화면은 결과를 짐작하지 않고, 처리 후 저장된 상태를 다시 읽어서 보여 준다.
"""
from __future__ import annotations

import streamlit as st

from src import service
from src.config import MAX_EDIT_ROUNDS, MAX_REGENERATIONS, OVERDUE_DAYS, RULE_NAMES
from src.generation import GenerationError, injection_options
from src.metrics import CRITERIA_COMBOS, evaluate_all
from src.sample_data import get_sample, list_samples
from src.validation import explain_rules
from ui.components import (
    ACTION_LABELS,
    GENERATION_MODE_LABELS,
    LAST_ACTION_LABELS,
    PUBLICATION_LABELS,
    STATUS_INFO,
    format_time,
    md_escape,
    rule_label,
    rules_hit,
    rules_text,
    review_styles,
    review_message,
    show_content,
    show_events,
    show_product,
    show_review_flags,
    show_table,
    status_label,
    warning_summary,
)

# 화면 이름 (사이드바 순서)
PAGE_DASHBOARD = "대시보드"
PAGE_NEW = "새 상품 등록"
PAGE_PENDING = "승인 대기함"
PAGE_DETAIL = "승인 상세"
PAGE_HISTORY = "처리 이력"
PAGE_CRITERIA = "승인 기준 검증"
PAGE_CATALOG = "데모 카탈로그"
PAGES = [PAGE_DASHBOARD, PAGE_NEW, PAGE_PENDING, PAGE_DETAIL, PAGE_HISTORY, PAGE_CRITERIA, PAGE_CATALOG]

# 세션 상태 키
NAV_KEY = "nav"  # 사이드바에서 고른 화면
SELECTED_KEY = "selected_submission"  # 승인 상세에서 볼 요청 ID
FLASH_KEY = "review_flash"  # 승인 상세에서 처리 직후 보여 줄 결과 문구
LAST_SUBMIT_KEY = "last_submit_id"  # 새 상품 등록에서 마지막으로 보낸 요청 ID
LOADED_SAMPLE_KEY = "loaded_sample_id"  # 양식에 불러온 샘플 ID
BATCH_KEY = "batch_result"  # 샘플 전체 실행 결과

EMPTY_PENDING_TEXT = "현재 승인 대기 중인 상품이 없습니다"
OLLAMA_HINT = "Ollama 서버가 켜져 있는지 확인하거나, 생성 방식을 '샘플 모드'로 바꿔 다시 시도해 주세요."

# 새 상품 등록 양식의 입력 칸 키와 기본값
FORM_DEFAULTS: dict[str, object] = {
    "f_product_id": "",
    "f_product_name": "",
    "f_category": "침구",
    "f_material": "",
    "f_colors": "",
    "f_sizes": "",
    "f_selling_price": "",
    "f_sale_price": "",
    "f_care_instructions": "",
    "f_approved_claims": "",
    "f_source_notes": "",
}


# ---------------------------------------------------------------------------
# 공통: 화면 이동과 배지
# ---------------------------------------------------------------------------
def go_to(page: str, submission_id: str | None = None) -> None:
    """버튼 콜백: 다른 화면으로 이동한다. 요청 ID를 주면 승인 상세에서 그 요청을 연다."""
    if submission_id:
        st.session_state[SELECTED_KEY] = submission_id
        st.session_state["review_request_pick"] = submission_id
    st.session_state[NAV_KEY] = page


def badges_markdown(status: str | None, overdue: bool = False) -> str:
    """상태 배지(+지연 배지)를 한 줄 마크다운으로 만든다. 문구는 고정값이라 안전하다."""
    label, color = STATUS_INFO.get(status or "", (status_label(status), "gray"))
    text = f":{color}-badge[{label}]"
    if overdue:
        text += " :red-badge[:material/schedule: 지연]"
    return text


def _pick(data: dict | None, *keys: str, default=None):
    """여러 후보 키 중 처음으로 값이 있는 것을 돌려준다."""
    for key in keys:
        if data and data.get(key) not in (None, ""):
            return data[key]
    return default


# ---------------------------------------------------------------------------
# 1. 대시보드
# ---------------------------------------------------------------------------
def render_dashboard() -> None:
    st.header("대시보드")
    st.caption(
        "등록 요청 → 콘텐츠 생성 → 자동 검증 → 문제가 없으면 데모 카탈로그에 자동 등록, "
        "확인이 필요하면 승인 대기함으로 보냅니다."
    )
    counts = service.dashboard_counts()

    with st.container(key="dashboard_metrics"):
        metrics = st.columns(7, gap="small")
        for column, (label, key) in zip(metrics, (
            ("전체 요청", "total"), ("자동 등록", "auto_published"),
            ("승인 대기", "pending_review"), ("승인 후 등록", "approved_published"),
            ("반려", "rejected"), ("처리 실패", "failed"), ("지연", "overdue"),
        )):
            column.metric(label, counts.get(key, 0))

    overdue = counts.get("overdue", 0)
    if overdue:
        st.warning(f"{OVERDUE_DAYS}일 넘게 승인을 기다리는 요청이 {overdue}건 있습니다. 지연 건도 자동 승인하지 않습니다.")
    pending = service.list_pending()
    if pending:
        with st.container(border=True, key="dashboard_reminder"):
            message, action = st.columns([4, 1.4], gap="medium", vertical_alignment="center")
            message.markdown(f"**승인을 기다리는 상품이 {len(pending)}건 있습니다.**")
            message.caption("원본과 다른 표현이 있는지 확인하고 다음 단계로 넘겨 주세요.")
            action.button("승인 대기함 열기", type="primary", on_click=go_to, args=(PAGE_PENDING,), key="dash_open_pending", width="stretch")
        st.subheader("지금 확인할 상품")
        for index, item in enumerate(pending[:3]):
            with st.container(border=True, key=f"dashboard_queue_{index}"):
                product, reason, action = st.columns([3, 3, 1.3], gap="medium", vertical_alignment="center")
                product.markdown(f"**{md_escape(item.get('product_name') or '-')}**")
                product.caption(f"접수 {format_time(item.get('created_at'))}")
                reason.text(warning_summary(item.get("validation_flags")), width="stretch")
                action.button("상세 보기", on_click=go_to, args=(PAGE_DETAIL, item["submission_id"]), key=f"dash_review_{item['submission_id']}", width="stretch")
    else:
        st.info("지금 확인할 승인 대기 상품이 없습니다. 새 상품을 등록하거나 샘플로 흐름을 확인해 보세요.")

    st.divider()
    st.subheader("샘플 전체 실행")
    st.caption("준비된 샘플 상품을 샘플 모드로 한 번에 등록 요청합니다. 결과는 각 화면에 그대로 쌓입니다.")
    if st.button("샘플 전체 실행", key="run_batch"):
        with st.spinner("샘플을 처리하는 중입니다..."):
            results = service.run_sample_batch()
        st.session_state[BATCH_KEY] = [
            {
                "샘플": r.get("sample_id") or "-",
                "요청 ID": r.get("submission_id", ""),
                "상품명": r.get("product_name", ""),
                "결과": status_label(r.get("status")),
                "걸린 기준": rules_text(r.get("validation_flags")),
            }
            for r in results
        ]
        st.rerun()

    batch = st.session_state.get(BATCH_KEY)
    if batch:
        st.success(f"샘플 {len(batch)}건을 처리했습니다.")
        show_table(batch)


# ---------------------------------------------------------------------------
# 2. 새 상품 등록
# ---------------------------------------------------------------------------
def _fill_from_sample() -> None:
    """버튼 콜백: 고른 샘플의 상품 정보로 양식을 채운다."""
    sample_id = st.session_state.get("sample_pick")
    if not sample_id:
        return
    product = get_sample(sample_id)["product"]
    st.session_state["f_product_id"] = product.get("product_id", "")
    st.session_state["f_product_name"] = product.get("product_name", "")
    st.session_state["f_category"] = product.get("category", "") or "침구"
    st.session_state["f_material"] = product.get("material", "")
    st.session_state["f_colors"] = ", ".join(product.get("colors") or [])
    st.session_state["f_sizes"] = ", ".join(product.get("sizes") or [])
    st.session_state["f_selling_price"] = _price_text(product.get("selling_price"))
    st.session_state["f_sale_price"] = _price_text(product.get("sale_price"))
    st.session_state["f_care_instructions"] = product.get("care_instructions", "")
    st.session_state["f_approved_claims"] = "\n".join(product.get("approved_claims") or [])
    st.session_state["f_source_notes"] = product.get("source_notes", "")
    st.session_state[LOADED_SAMPLE_KEY] = sample_id
    st.session_state[LAST_SUBMIT_KEY] = None


def _clear_form() -> None:
    """버튼 콜백: 양식을 비운다."""
    for key, value in FORM_DEFAULTS.items():
        st.session_state[key] = value
    st.session_state[LOADED_SAMPLE_KEY] = None
    st.session_state[LAST_SUBMIT_KEY] = None


def _price_text(value: object) -> str:
    return "" if value in (None, "") else f"{int(value):,}"


def _parse_price(text: str, label: str) -> int | None:
    """'59,000' 또는 '59000원' 형태를 정수로 바꾼다. 비어 있으면 None."""
    cleaned = text.replace(",", "").replace("원", "").strip()
    if not cleaned:
        return None
    if not cleaned.isdigit():
        raise ValueError(f"{label}은(는) 숫자로 입력해 주세요. 예: 59,000")
    return int(cleaned)


def _split_lines(text: str) -> list[str]:
    return [part.strip() for part in text.replace("\n", ",").split(",") if part.strip()]


def _build_product() -> dict:
    """양식 입력값으로 원본 상품 정보 dict를 만든다. 형식이 틀리면 ValueError."""
    s = st.session_state
    if not s["f_product_id"].strip() or not s["f_product_name"].strip():
        raise ValueError("상품 ID와 상품명은 반드시 입력해야 합니다.")
    return {
        "product_id": s["f_product_id"].strip(),
        "product_name": s["f_product_name"].strip(),
        "category": s["f_category"].strip() or "침구",
        "material": s["f_material"].strip(),
        "colors": _split_lines(s["f_colors"]),
        "sizes": _split_lines(s["f_sizes"]),
        "selling_price": _parse_price(s["f_selling_price"], "정상 판매가"),
        "sale_price": _parse_price(s["f_sale_price"], "할인가"),
        "care_instructions": s["f_care_instructions"].strip(),
        "approved_claims": _split_lines(s["f_approved_claims"]),
        "source_notes": s["f_source_notes"].strip(),
    }


def _submit_form(mode: str, injection: str | None, use_sample: bool) -> None:
    """양식을 서비스에 보내고, 결과 요청 ID를 기억한다. 오류는 한국어로 보여 준다."""
    try:
        product = _build_product()
    except ValueError as exc:
        st.error(str(exc))
        return
    sample_id = st.session_state.get(LOADED_SAMPLE_KEY) if use_sample else None
    try:
        with st.spinner("콘텐츠를 생성하고 검증하는 중입니다..."):
            result = service.submit_product(
                product,
                mode=mode,
                sample_id=sample_id,
                injection=None if (sample_id or injection in (None, "none")) else injection,
            )
    except ValueError as exc:
        st.error(f"입력값을 확인해 주세요: {exc}")
        return
    except GenerationError as exc:
        st.error(f"콘텐츠를 생성하지 못했습니다: {exc}")
        if mode == "ollama":
            st.info(OLLAMA_HINT)
        return
    st.session_state[LAST_SUBMIT_KEY] = result.get("submission_id")


def _show_submit_result() -> None:
    """마지막 등록 요청의 실제 저장 상태를 다시 읽어 결과를 보여 준다."""
    submission_id = st.session_state.get(LAST_SUBMIT_KEY)
    if not submission_id:
        return
    sub = service.get_submission(submission_id)
    if not sub:
        st.error("방금 보낸 요청을 찾을 수 없습니다.")
        return
    st.divider()
    st.subheader("처리 결과")
    st.markdown(f"{badges_markdown(sub.get('status'), sub.get('overdue', False))}  요청 ID `{sub['submission_id']}`")
    status = sub.get("status")
    flags = sub.get("validation_flags") or []
    if status == "auto_published":
        st.success("검증에서 문제가 발견되지 않아 데모 카탈로그에 자동 등록했습니다.")
        st.button("데모 카탈로그 보기", on_click=go_to, args=(PAGE_CATALOG,), key="result_catalog")
    elif status == "pending_review":
        st.warning("확인이 필요한 내용이 발견되어 자동 등록하지 않고 승인 대기함으로 보냈습니다.")
        st.markdown("**멈춘 이유**")
        for flag in flags:
            st.markdown(f"- **{md_escape(rule_label(flag.get('rule', '')))}**: {md_escape(flag.get('message', ''))}")
        st.button("승인 상세 열기", on_click=go_to, args=(PAGE_DETAIL, submission_id), key="result_detail")
    elif status == "failed":
        st.error(f"처리에 실패해 등록하지 않았습니다: {md_escape(sub.get('error_message') or '원인 미상')}")
        if sub.get("generation_mode") == "ollama":
            st.info(OLLAMA_HINT)
    else:
        st.info(f"현재 상태: {status_label(status)}")


def render_new_product() -> None:
    st.header("새 상품 등록")

    # 페이지를 떠났다 오면 입력 칸은 비워지므로, 불러온 샘플 표시도 함께 지운다.
    if "f_product_id" not in st.session_state:
        st.session_state[LOADED_SAMPLE_KEY] = None
    for key, value in FORM_DEFAULTS.items():
        st.session_state.setdefault(key, value)

    with st.container(border=True, key="new_sample_controls"):
        st.markdown("**샘플 불러오기**")
        samples = list_samples()
        titles = {s["sample_id"]: f"{s['sample_id']} · {s['title']} ({s.get('group', '기본')})" for s in samples}
        cols = st.columns([4, 1.3, 1])
        cols[0].selectbox(
            "샘플 선택",
            [None, *titles.keys()],
            format_func=lambda sid: "선택 안 함" if sid is None else titles[sid],
            key="sample_pick",
            label_visibility="collapsed",
        )
        cols[1].button(
            "이 샘플로 채우기",
            on_click=_fill_from_sample,
            disabled=not st.session_state.get("sample_pick"),
            key="fill_sample",
            width="stretch",
        )
        cols[2].button("양식 비우기", on_click=_clear_form, key="clear_form", width="stretch")
        loaded = st.session_state.get(LOADED_SAMPLE_KEY)
        if loaded:
            st.caption(f"불러온 샘플: {md_escape(titles.get(loaded, loaded))}")

    st.caption(
        "\\* 표시는 반드시 입력해야 합니다. '필수 정보' 칸(소재·색상·사이즈·관리 방법)이 비어 있으면 "
        "자동 등록하지 않고 승인 대기함으로 보냅니다."
    )
    with st.form("product_form"):
        st.markdown("#### 기본 상품 정보")
        c1, c2 = st.columns(2)
        c1.text_input("상품 ID \\*", key="f_product_id", placeholder="예: GH-BED-001")
        c2.text_input("상품명 \\*", key="f_product_name", placeholder="예: 데일리 순면 차렵이불")
        c1.text_input("카테고리", key="f_category", placeholder="예: 침구")
        c2.text_input("소재 (필수 정보)", key="f_material", placeholder="예: 면 100%")
        c1.text_input("색상 (필수 정보, 쉼표로 구분)", key="f_colors", placeholder="예: 아이보리, 그레이")
        c2.text_input("사이즈 (필수 정보, 쉼표로 구분)", key="f_sizes", placeholder="예: 싱글, 퀸")
        st.markdown("#### 가격과 근거")
        price1, price2 = st.columns(2)
        price1.text_input("정상 판매가 (원)", key="f_selling_price", placeholder="예: 79,000")
        price2.text_input("할인가 (원, 없으면 비워 두기)", key="f_sale_price", placeholder="예: 59,000")
        st.text_area("관리 방법 (필수 정보)", key="f_care_instructions", placeholder="예: 30도 이하 단독 세탁")
        st.text_area(
            "입증된 기능 표현 (근거 자료가 있는 것만, 한 줄에 하나)",
            key="f_approved_claims",
            placeholder="예: 정전기 방지 가공",
        )
        st.text_area("참고 자료", key="f_source_notes", placeholder="공급처 자료, 구성품 등 근거가 되는 내용")

        st.markdown("**생성 설정**")
        g1, g2 = st.columns(2)
        mode = g1.radio(
            "생성 방식",
            ["sample", "ollama"],
            format_func=lambda m: GENERATION_MODE_LABELS[m],
            horizontal=True,
            key="f_mode",
        )
        options = injection_options()
        option_labels = dict(options)
        injection = g2.selectbox(
            "데모용 위험 문구 넣기",
            [oid for oid, _ in options],
            format_func=lambda oid: option_labels.get(oid, oid),
            key="f_injection",
            help="직접 입력한 상품에 일부러 위험한 표현을 넣어 승인 대기 흐름을 확인할 때 씁니다.",
        )
        use_sample = False
        if loaded:
            use_sample = st.checkbox(
                f"불러온 샘플({loaded})의 시나리오를 그대로 적용 (위험 문구 선택은 무시)",
                value=True,
                key="f_use_sample",
            )
        submitted = st.form_submit_button("등록 요청", type="primary")

    if submitted:
        _submit_form(mode, injection, use_sample)
    _show_submit_result()


# ---------------------------------------------------------------------------
# 3. 승인 대기함
# ---------------------------------------------------------------------------
def render_pending() -> None:
    st.header("승인 대기함")
    review_styles()
    with st.container(key="review_workspace"):
        _pending_workspace()


def _clear_pending_filters() -> None:
    st.session_state["pending_search"] = ""
    st.session_state["pending_scope"] = "전체"
    st.session_state["pending_rule"] = "전체 기준"


def _pending_workspace() -> None:
    st.caption(f"확인이 필요한 상품을 선택하세요. {OVERDUE_DAYS}일 초과 지연 건부터, 접수된 순서로 표시합니다.")
    pending = service.list_pending()
    if not pending:
        st.info(EMPTY_PENDING_TEXT)
        return
    st.markdown(f"대기 중 **{len(pending)}건**")
    with st.container(border=True, key="pending_filters"):
        search_col, scope_col, rule_col = st.columns([2, 1, 1.5], gap="medium")
        query = search_col.text_input(
            "상품 검색", placeholder="상품명 · 상품 ID · 요청 ID", key="pending_search"
        ).strip().casefold()
        scope = scope_col.radio("대기 구분", ["전체", "지연만"], horizontal=True, key="pending_scope")
        available_rules = [r for r in RULE_NAMES if any(r in rules_hit(p.get("validation_flags")) for p in pending)]
        filter_options = ["전체 기준", *available_rules]
        if st.session_state.get("pending_rule") not in filter_options:
            st.session_state["pending_rule"] = "전체 기준"
        rule = rule_col.selectbox(
            "확인 기준", filter_options,
            format_func=lambda r: rule_label(r) if r in RULE_NAMES else r,
            key="pending_rule",
        )
    visible = [
        p for p in pending
        if (scope != "지연만" or p.get("overdue"))
        and (rule == "전체 기준" or rule in rules_hit(p.get("validation_flags")))
        and (not query or query in " ".join(str(p.get(k) or "") for k in ("product_name", "product_id", "submission_id")).casefold())
    ]
    st.caption(f"표시 {len(visible)}건 / 전체 {len(pending)}건")
    if query or scope != "전체" or rule != "전체 기준":
        st.button("검색·필터 초기화", on_click=_clear_pending_filters, key="pending_reset")
    if not visible:
        st.info("선택한 조건에 맞는 상품이 없습니다. 검색어나 필터를 바꿔 주세요.")
        return
    for item in visible:
        sid = item["submission_id"]
        flags = item.get("validation_flags") or []
        with st.container(border=True, key=f"pending_card_{sid}"):
            st.markdown(
                f"**{md_escape(item.get('product_name', ''))}**  "
                f"{badges_markdown(item.get('status'), item.get('overdue', False))}"
            )
            st.text(warning_summary(flags), width="stretch")
            st.caption(f"걸린 기준: {md_escape(rules_text(flags))}")
            meta, action = st.columns([3, 1], gap="medium", vertical_alignment="bottom")
            with meta:
                st.caption(f"접수 {format_time(item.get('created_at'))} · 상품 ID {md_escape(item.get('product_id', ''))}")
                st.caption(f"요청 ID {md_escape(sid)}")
            action.button("상세 보기", key=f"open_{sid}", on_click=go_to, args=(PAGE_DETAIL, sid), width="stretch")


# ---------------------------------------------------------------------------
# 4. 승인 상세
# ---------------------------------------------------------------------------
def _approval_sentence(payload: dict | None, content: dict | None) -> str:
    """승인 시 결과 문장: 어떤 제목으로 등록되는지 + 체크포인트에 담긴 가격 안내."""
    title = (content or {}).get("display_title") or "(제목 없음)"
    sentence = f"승인하면 이 콘텐츠가 데모 카탈로그에 '{title}'(으)로 등록됩니다 (실제 쇼핑몰에는 등록되지 않습니다)."
    extra = _pick(payload, "approve_result_text")
    if isinstance(extra, str):
        extra = extra.removeprefix("승인하면 지금 콘텐츠가 데모 카탈로그에 게시됩니다.").strip()
    return f"{sentence} {extra}" if isinstance(extra, str) and extra.strip() else sentence


def _flash_for(submission_id: str, before: dict, action: str, result: dict | None) -> dict:
    """처리 후 다시 읽은 실제 상태로 결과 문구를 만든다(성공을 짐작하지 않는다)."""
    fresh = service.get_submission(submission_id) or {}
    status = fresh.get("status")
    review_error = (result or {}).get("review_error")
    name = fresh.get("product_name") or before.get("product_name", "")
    if status == "pending_review" and review_error:
        return {"kind": "error", "text": f"응답이 반영되지 않았습니다: {review_error}"}
    if status == "pending_review":
        return {"kind": "warning", "text": f"'{name}'을(를) 다시 검증한 결과, 여전히 승인이 필요합니다. 아래 내용을 다시 확인해 주세요."}
    if status in ("approved_published", "auto_published"):
        how = {
            "reassess": "다시 판정한 결과 문제가 없어",
            "approve_with_edits": "수정한 내용을 다시 검증한 결과 문제가 없어",
        }.get(action, "승인해")
        return {"kind": "success", "text": f"'{name}'을(를) {how} 데모 카탈로그에 등록했습니다. (현재 상태: {status_label(status)})"}
    if status == "rejected":
        return {"kind": "info", "text": f"'{name}' 요청을 반려했습니다. 데모 카탈로그에는 등록하지 않았습니다."}
    if status == "failed":
        hint = f" {OLLAMA_HINT}" if fresh.get("generation_mode") == "ollama" else ""
        return {"kind": "error", "text": f"처리 중 오류가 발생해 등록하지 않았습니다: {fresh.get('error_message') or '원인 미상'}{hint}"}
    return {"kind": "info", "text": f"현재 상태: {status_label(status)}"}


def _send_response(submission_id: str, submission: dict, response: dict) -> None:
    """응답을 그래프에 넘기고, 저장된 실제 결과를 다음 화면에 보여 주도록 기록한다."""
    try:
        with st.spinner("응답을 반영하는 중입니다..."):
            result = service.respond(submission_id, response)
    except ValueError as exc:
        st.session_state[FLASH_KEY] = {"sid": submission_id, "kind": "error", "text": str(exc)}
    except GenerationError as exc:
        st.session_state[FLASH_KEY] = {
            "sid": submission_id,
            "kind": "error",
            "text": f"다시 생성하지 못했습니다: {exc} — {OLLAMA_HINT}",
        }
    else:
        flash = _flash_for(submission_id, submission, response.get("action", ""), result)
        st.session_state[FLASH_KEY] = {"sid": submission_id, **flash}
    st.rerun()


def _show_flash(submission_id: str) -> None:
    flash = st.session_state.get(FLASH_KEY)
    if not flash or flash.get("sid") != submission_id:
        return
    show = {"success": st.success, "warning": st.warning, "error": st.error}.get(flash["kind"], st.info)
    show(md_escape(flash["text"]))


def _limits(payload: dict, submission: dict) -> tuple[int, int, bool]:
    """다시 판정·수정 횟수와 '승인 사유 필수' 여부."""
    limits = payload.get("limits") or {}
    regen = int(limits.get("regeneration_count", submission.get("regeneration_count") or 0))
    edits = int(limits.get("edit_round", submission.get("edit_round") or 0))
    return regen, edits, bool(limits.get("approve_requires_reason"))


def _response_form(sid: str, submission: dict, payload: dict, content: dict) -> None:
    """승인 / 수정 후 승인 / 반려 / 다시 판정 입력 화면."""
    allowed = [a for a in (payload.get("allowed_actions") or []) if a in ACTION_LABELS]
    regen, edits, requires_reason = _limits(payload, submission)
    limits = payload.get("limits") or {}
    max_regen = limits.get("max_regenerations", MAX_REGENERATIONS)
    max_edits = limits.get("max_edit_rounds", MAX_EDIT_ROUNDS)
    st.caption(
        f"다시 판정 {regen}/{max_regen}회 · 수정 후 승인 {edits}/{max_edits}회 사용"
    )
    if not allowed:
        st.error("가능한 처리 방법을 불러오지 못했습니다. 요청을 다시 선택해 주세요.")
        return
    if "approve" not in allowed:
        st.warning("이 요청은 바로 승인할 수 없습니다. 아래에서 가능한 처리 방법을 선택해 주세요.")
    if limits.get("regeneration_limit_reached"):
        st.caption("다시 판정은 사용 상한에 도달했습니다.")
    if limits.get("edit_limit_reached"):
        st.caption("수정 후 승인은 사용 상한에 도달했습니다.")
    if requires_reason:
        st.warning("반복 상한에 도달했습니다. 승인하려면 승인 사유(책임 승인 메모)를 반드시 적어야 합니다.")
    review_error = payload.get("review_error")
    flash = st.session_state.get(FLASH_KEY) or {}
    if review_error and flash.get("sid") != sid:  # 방금 보낸 응답의 오류는 위 안내에서 이미 보여 준다
        st.error(md_escape(f"이전 응답이 반영되지 않았습니다: {review_error}"))

    tag = f"{sid}_{regen}_{edits}"  # 다시 판정·수정 뒤에는 입력 칸을 새 내용으로 초기화한다
    reviewer = st.text_input("담당자 이름", value="운영 담당자", key=f"reviewer_{tag}")
    if st.session_state.get(f"action_{tag}") not in allowed:
        st.session_state[f"action_{tag}"] = allowed[0]
    action = st.radio(
        "처리 방법",
        allowed,
        format_func=lambda a: ACTION_LABELS[a],
        horizontal=False,
        key=f"action_{tag}",
        width="stretch",
    )
    base = {"action": action, "reviewer": reviewer.strip() or "운영 담당자"}

    if action == "approve":
        label = "승인 사유 (필수)" if requires_reason else "승인 메모 (선택)"
        reason = st.text_area(label, key=f"approve_reason_{tag}")
        missing = requires_reason and not reason.strip()
        if missing:
            st.caption("승인 사유를 입력해야 승인할 수 있습니다.")
        if st.button("승인하기", type="primary", disabled=missing, key=f"btn_approve_{tag}", width="stretch"):
            _send_response(sid, submission, {**base, "reason": reason.strip()})

    elif action == "approve_with_edits":
        title = st.text_input("상품 제목", value=content.get("display_title", ""), key=f"edit_title_{tag}")
        summary = st.text_input("한 줄 요약", value=content.get("one_line_summary", ""), key=f"edit_summary_{tag}")
        description = st.text_area(
            "상세 설명", value=content.get("detail_description", ""), height=200, key=f"edit_desc_{tag}"
        )
        points_text = st.text_area(
            "핵심 장점 (한 줄에 하나)",
            value="\n".join(content.get("selling_points") or []),
            key=f"edit_points_{tag}",
        )
        st.caption("수정한 내용은 다시 자동 검증한 뒤 등록합니다. 가격은 원본 값을 그대로 씁니다.")
        points = [p.strip() for p in points_text.splitlines() if p.strip()]
        missing = not (title.strip() and summary.strip() and description.strip() and points)
        if missing:
            st.caption("제목·한 줄 요약·상세 설명·핵심 장점(1개 이상)을 모두 채워야 합니다.")
        if st.button("수정 내용으로 승인", type="primary", disabled=missing, key=f"btn_edit_{tag}", width="stretch"):
            edits_payload = {
                "display_title": title.strip(),
                "one_line_summary": summary.strip(),
                "detail_description": description.strip(),
                "selling_points": points,
            }
            _send_response(sid, submission, {**base, "edits": edits_payload})

    elif action == "reject":
        reason = st.text_area("반려 사유 (필수)", key=f"reject_reason_{tag}")
        missing = not reason.strip()
        if missing:
            st.caption("반려 사유를 입력해야 반려할 수 있습니다.")
        if st.button("반려하기", type="primary", disabled=missing, key=f"btn_reject_{tag}", width="stretch"):
            _send_response(sid, submission, {**base, "reason": reason.strip()})

    elif action == "reassess":
        instructions = st.text_area(
            "다시 작성 지시",
            value="원본 상품 정보에 있는 내용만 사용해 다시 작성해 주세요.",
            key=f"reassess_{tag}",
        )
        st.caption("콘텐츠를 다시 생성하고 자동 검증을 다시 실행합니다.")
        if st.button("다시 판정 요청", type="primary", key=f"btn_reassess_{tag}", width="stretch"):
            _send_response(sid, submission, {**base, "instructions": instructions.strip()})


def render_review_detail() -> None:
    st.header("승인 상세")
    review_styles()
    with st.container(key="review_workspace"):
        _review_workspace()


def _review_workspace() -> None:
    pending = service.list_pending()
    selected = st.session_state.get(SELECTED_KEY)
    options = [p["submission_id"] for p in pending]
    if selected and selected not in options:
        options = [selected, *options]  # 방금 처리한 요청도 결과를 볼 수 있게 남겨 둔다
    if not options:
        st.info(EMPTY_PENDING_TEXT)
        return
    names = {p["submission_id"]: p.get("product_name", "") for p in pending}
    if st.session_state.get("review_request_pick") not in options:
        st.session_state["review_request_pick"] = selected if selected in options else options[0]
    with st.container(key="review_toolbar"):
        picker, back = st.columns([3, 1], gap="medium", vertical_alignment="bottom")
        chosen = picker.selectbox(
            "검토할 요청", options,
            format_func=lambda sid: f"{names.get(sid) or '처리된 요청'} · {sid}",
            key="review_request_pick",
        )
        back.button("대기함으로", on_click=go_to, args=(PAGE_PENDING,), width="stretch", key="detail_back")
    st.session_state[SELECTED_KEY] = chosen

    submission = service.get_submission(chosen)
    if not submission:
        st.error("요청을 찾을 수 없습니다.")
        return
    _show_flash(chosen)

    status = submission.get("status")
    # 승인 대기 중이면 화면 내용은 체크포인트(멈춘 지점)에서 다시 읽는다.
    payload = service.get_review_payload(chosen) if status == "pending_review" else None
    product = _pick(payload, "product") or submission.get("product_input") or {}
    content = _pick(payload, "content") or submission.get("generated_content") or {}
    flags = payload["flags"] if payload and "flags" in payload else (submission.get("validation_flags") or [])

    st.markdown(f"### {md_escape(submission.get('product_name') or product.get('product_name') or '-')}")
    st.markdown(badges_markdown(status, submission.get("overdue", False)))
    mode = GENERATION_MODE_LABELS.get(submission.get("generation_mode") or "", "-")
    st.caption(
        f"접수 {format_time(submission.get('created_at'))} · 생성 방식 {md_escape(mode)} · "
        f"요청 ID {md_escape(chosen)} · 샘플 {md_escape(submission.get('sample_id') or '직접 입력')}"
    )

    if status != "pending_review":
        st.markdown("#### 처리 결과")
        st.info(f"이 요청은 이미 처리되었습니다. 현재 상태: {status_label(status)}")
        if submission.get("rejection_reason"):
            st.text(f"반려 사유: {submission['rejection_reason']}", width="stretch")
        remaining = [p for p in pending if p["submission_id"] != chosen]
        if remaining:
            st.button(
                "다음 대기 건 보기", type="primary", on_click=go_to,
                args=(PAGE_DETAIL, remaining[0]["submission_id"]), key="detail_next",
            )
        else:
            st.caption("남아 있는 승인 대기 건이 없습니다.")
        st.markdown("#### 마지막 검증 근거")
        show_review_flags(flags)
        _review_source(product, content)
        if submission.get("final_content"):
            with st.expander("최종 등록 콘텐츠"):
                show_content(submission["final_content"])
        with st.expander("처리 이력"):
            show_events(submission.get("events"))
        return

    if payload is None:
        st.error("멈춘 지점의 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.")
        _review_source(product, content)
        return

    hit_rules = rules_hit(flags)
    with st.container(key="review_decision_grid"):
        evidence, response = st.columns([1.65, 1], gap="medium")
        with evidence:
            st.markdown("#### 멈춘 이유")
            if flags:
                st.warning(f"확인 필요 {len(flags)}건 · 걸린 기준 {', '.join(hit_rules)}")
                explanations = explain_rules()
                for rule in hit_rules:
                    st.markdown(f"**{md_escape(rule_label(rule))}**")
                    st.text(explanations.get(rule, "기준 설명이 없습니다."), width="stretch")
                    messages = dict.fromkeys(review_message(f.get("message")) for f in flags if f.get("rule") == rule)
                    for message in messages:
                        if message:
                            st.text(message, width="stretch")
            else:
                st.warning("멈춘 이유가 기록되지 않았습니다. 원문과 생성 결과를 확인해 주세요.")
            st.markdown("#### 검증 근거")
            st.caption("원본 값·AI가 쓴 값·근거 문장을 항목별로 비교하세요.")
            show_review_flags(flags)
        with response:
            with st.container(border=True, key="review_response"):
                st.markdown("#### 승인 시 결과")
                st.info(md_escape(_approval_sentence(payload, content)))
                st.markdown("#### 응답")
                _response_form(chosen, submission, payload, content)
    _review_source(product, content)


def _review_source(product: dict, content: dict) -> None:
    """판단 요약 아래에 요청 원문과 생성 결과 전체를 항상 펼쳐 둔다."""
    st.divider()
    st.caption("아래에서 요청 원문과 생성 결과 전체를 확인할 수 있습니다.")
    with st.container(key="review_source_grid"):
        source, generated = st.columns(2, gap="medium")
        with source:
            st.markdown("#### 요청 원문")
            with st.container(border=True, key="review_original"):
                show_product(product)
        with generated:
            st.markdown("#### AI 생성 결과")
            with st.container(border=True, key="review_generated"):
                show_content(content)


# ---------------------------------------------------------------------------
# 5. 처리 이력
# ---------------------------------------------------------------------------
def render_history() -> None:
    st.header("처리 이력")
    status = st.selectbox(
        "상태로 거르기",
        [None, *STATUS_INFO.keys()],
        format_func=lambda s: "전체" if s is None else status_label(s),
        key="history_filter",
    )
    items = service.list_history(status)
    if not items:
        st.info("해당하는 처리 이력이 없습니다.")
        return
    show_table(
        [
            {
                "상품명": it.get("product_name", ""),
                "상태": status_label(it.get("status")),
                "지연": "지연" if it.get("overdue") else "",
                "최근 처리": format_time(it.get("updated_at")),
                "마지막 처리": LAST_ACTION_LABELS.get(it.get("last_action") or "", it.get("last_action") or "-"),
            }
            for it in items
        ]
    )
    st.markdown("#### 요청별 처리 흐름")
    for it in items:
        sid = it.get("submission_id", "")
        label = f"{md_escape(it.get('product_name', ''))} · {sid} · {status_label(it.get('status'))}"
        with st.expander(label):
            st.caption(f"요청 ID {md_escape(sid)} · 접수 {format_time(it.get('created_at'))}")
            st.caption(f"생성 방식: {md_escape(GENERATION_MODE_LABELS.get(it.get('generation_mode') or '', '-'))}")
            events = it.get("events")
            if events is None:
                events = (service.get_submission(sid) or {}).get("events")
            show_events(events)
            if it.get("rejection_reason"):
                st.text(f"반려 사유: {it['rejection_reason']}")
            if it.get("error_message"):
                st.text(f"오류: {it['error_message']}")


# ---------------------------------------------------------------------------
# 6. 승인 기준 검증
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="기준 조합별로 샘플을 평가하는 중입니다...")
def _evaluate(dataset: str = "samples") -> list[dict]:
    return evaluate_all(dataset)


def _row_result(row: dict) -> str:
    """사람 판단과 기준 판단을 비교한 결과 문구."""
    expected, actual = bool(row.get("expected")), bool(row.get("actual"))
    if expected == actual:
        return "일치"
    return "놓침" if expected else "헛멈춤"


def render_criteria() -> None:
    st.header("승인 기준 검증")
    st.caption(
        "각 데이터의 '사람이라면 멈춰야 하는가'와 기준 조합별 판단을 비교합니다. "
        "놓침 = 멈췄어야 하는데 통과시킨 건(위험), 헛멈춤 = 멈출 필요가 없는데 멈춘 건(업무 부담)."
    )
    datasets = {
        "samples": "고정 샘플 20건",
        "llm": "로컬 모델 실제 출력 20건",
        "holdout": "처음 보는 모델 출력 20건",
    }
    dataset = st.selectbox("평가 데이터", list(datasets), format_func=datasets.get, key="criteria_dataset")
    st.caption({
        "samples": "준비된 상품 시나리오로 기준 조합을 비교합니다.",
        "llm": "기준 E를 만들 때 참고한 실제 출력 기록입니다. 새로 생성하지 않습니다.",
        "holdout": "규칙을 적용하기 전에 정답을 붙인 별도 출력 기록입니다. 새로 생성하지 않습니다.",
    }[dataset])
    results = _evaluate(dataset)
    baselines = {c["key"] for c in CRITERIA_COMBOS if c.get("baseline")}  # 비교용 기준선(없음·전부 멈춤)
    total = results[0].get("total", 0) if results else 0
    st.warning(
        f"샘플 {total}건으로 계산한 값입니다. 표본이 작아 이 샘플 묶음에 대한 결과일 뿐, 실제 운영 성능으로 일반화할 수 없습니다."
    )
    final = next((result for result in results if "(최종)" in result.get("label", "")), None)
    if final:
        with st.container(border=True, key="criteria_final"):
            st.markdown(f"**{md_escape(final['label'])}**")
            metrics = st.columns(3)
            metrics[0].metric("최종 조합 개입률", f"{final.get('intervention_rate', 0):.1f}%")
            metrics[1].metric("놓침", final.get("missed", 0))
            metrics[2].metric("헛멈춤", final.get("false_stops", 0))
    show_table(
        [
            {
                "기준 조합": r.get("label", r.get("key", "")),
                "구분": "최종" if r is final else ("기준선" if r.get("key") in baselines else "후보"),
                "멈춤": f"{r.get('stopped', 0)}/{r.get('total', 0)}",
                "개입률": f"{float(r.get('intervention_rate', 0)):.1f}%",
                "놓침": r.get("missed", 0),
                "헛멈춤": r.get("false_stops", 0),
            }
            for r in results
        ]
    )

    st.markdown("#### 조합별 샘플 판정")
    for r in results:
        with st.expander(f"{md_escape(r.get('label', r.get('key', '')))} — 놓침 {r.get('missed', 0)} · 헛멈춤 {r.get('false_stops', 0)}"):
            st.text(f"놓친 샘플: {', '.join(r.get('missed_ids') or []) or '-'}", width="stretch")
            st.text(f"헛멈춘 샘플: {', '.join(r.get('false_stop_ids') or []) or '-'}", width="stretch")
            show_table(
                [
                    {
                        "샘플": row.get("sample_id", ""),
                        "시나리오": row.get("title", ""),
                        "사람 판단": "멈춤" if row.get("expected") else "통과",
                        "기준 판단": "멈춤" if row.get("actual") else "통과",
                        "비교": _row_result(row),
                        "걸린 기준": ", ".join(row.get("flags_rules") or []) or "-",
                    }
                    for row in r.get("rows") or []
                ]
            )

    st.markdown("#### 기준 설명")
    for rule, text in explain_rules().items():
        st.markdown(f"- **{md_escape(rule_label(rule))}**: {md_escape(text)}")


# ---------------------------------------------------------------------------
# 7. 데모 카탈로그
# ---------------------------------------------------------------------------
def _toggle_catalog(item_id: str) -> None:
    """저장된 콘텐츠는 변경하지 않고 펼침 상태만 바꾼다."""
    opened = set(st.session_state.get("catalog_expanded", []))
    if item_id in opened:
        opened.remove(item_id)
    else:
        opened.add(item_id)
    st.session_state["catalog_expanded"] = sorted(opened)


def render_catalog() -> None:
    st.header("데모 카탈로그")
    st.caption("실제 쇼핑몰이 아니라, 등록 결과를 확인하기 위한 데모 목록입니다.")
    items = service.list_catalog()
    if not items:
        st.info("아직 등록된 상품이 없습니다.")
        return
    st.markdown(f"등록 **{len(items)}건**")
    for index, item in enumerate(items):
        content = item.get("final_content") or {}
        ptype = PUBLICATION_LABELS.get(str(item.get("publication_type", "")), str(item.get("publication_type", "-")))
        item_id = str(item.get("submission_id") or item.get("product_id") or index)
        opened = item_id in st.session_state.get("catalog_expanded", [])
        with st.container(border=True, key=f"catalog_item_{index}"):
            with st.container(key=f"catalog_row_{index}"):
                product, price, method, action = st.columns([4.5, 1.6, 1.3, 1.9], gap="medium", vertical_alignment="center")
                product.markdown(f"**{md_escape(content.get('display_title') or item.get('product_name', ''))}**")
                product.caption(f"상품 ID {md_escape(item.get('product_id', ''))} · 등록 {format_time(item.get('published_at'))}")
                price.text(content.get("price_display") or "가격 표시 없음", width="stretch")
                method.badge(ptype, color="green")
                action.button(
                    "콘텐츠 접기" if opened else "콘텐츠 전체 보기",
                    on_click=_toggle_catalog, args=(item_id,), key=f"catalog_toggle_{index}", width="stretch",
                )
            if opened:
                st.divider()
                st.caption(f"요청 ID {md_escape(item.get('submission_id', ''))} · 등록 방식 {md_escape(ptype)}")
                with st.container(key=f"catalog_content_{index}"):
                    show_content(content, wide=True)


# 화면 이름 → 그리는 함수
RENDERERS = {
    PAGE_DASHBOARD: render_dashboard,
    PAGE_NEW: render_new_product,
    PAGE_PENDING: render_pending,
    PAGE_DETAIL: render_review_detail,
    PAGE_HISTORY: render_history,
    PAGE_CRITERIA: render_criteria,
    PAGE_CATALOG: render_catalog,
}
