"""LangGraph 그래프의 단계(node) 함수들.

함수 하나 = 처리 단계 하나. 각 함수는 상태(state)를 받아 바뀐 값만 돌려준다.
DB 기록은 함수 안에서 repository 함수로 한다.

중요: human_review 단계는 재개(resume)될 때 첫 줄부터 다시 실행된다.
그래서 human_review 안에서는 DB 기록 같은 부수 효과를 절대 만들지 않고,
대기 상태 저장은 바로 앞의 mark_pending 단계가 맡는다.
"""
from __future__ import annotations

from typing import Optional

from langgraph.types import interrupt

from src import config, generation, repository, validation
from src.schemas import ProductInput, PublisherState

# 승인 담당자가 고칠 수 있는 필드 (가격·소재 같은 사실 정보는 원본에서만 온다)
EDITABLE_FIELDS = ("display_title", "one_line_summary", "detail_description", "selling_points")

ALL_ACTIONS = ("approve", "approve_with_edits", "reject", "reassess")

# 다시 판정 지시를 비워 보냈을 때 쓰는 기본 지시
DEFAULT_REASSESS_INSTRUCTIONS = "원본 상품 정보에 있는 내용만 사용해 다시 작성해 주세요."


class GraphState(PublisherState, total=False):
    """그래프 상태. 공통 상태에 '응답 오류 메시지'를 더한다."""

    review_error: Optional[str]


# ---------------------------------------------------------------------------
# 작은 도우미 함수
# ---------------------------------------------------------------------------

def _format_won(value: int) -> str:
    return f"{value:,}원"


def price_display_from_product(product: dict) -> Optional[str]:
    """게시용 가격 문구를 원본 가격으로만 만든다(AI가 쓴 가격은 쓰지 않는다)."""
    selling = product.get("selling_price")
    sale = product.get("sale_price")
    if selling and sale and sale != selling:
        return f"정상가 {_format_won(selling)} → 할인가 {_format_won(sale)}"
    if sale:
        return _format_won(sale)
    if selling:
        return _format_won(selling)
    return None


def _rules_text(flags: list[dict]) -> str:
    """플래그 목록을 'A(핵심 상품 정보 불일치), B(...)' 같은 짧은 글로 만든다."""
    rules = sorted({flag.get("rule", "") for flag in flags})
    return ", ".join(f"{rule}({config.RULE_NAMES.get(rule, rule)})" for rule in rules)


def _human_note(response: dict, text: str) -> str:
    """담당자 이름이 있으면 기록 앞에 붙인다."""
    reviewer = str(response.get("reviewer") or "").strip()
    return f"[{reviewer}] {text}" if reviewer else text


def _limits(state: GraphState) -> dict:
    """반복 상한 정보. 승인 화면과 응답 검사에서 같이 쓴다."""
    regen = state.get("regeneration_count", 0)
    edits = state.get("edit_round", 0)
    regen_limit = regen >= config.MAX_REGENERATIONS
    edit_limit = edits >= config.MAX_EDIT_ROUNDS
    return {
        "regeneration_count": regen,
        "max_regenerations": config.MAX_REGENERATIONS,
        "edit_round": edits,
        "max_edit_rounds": config.MAX_EDIT_ROUNDS,
        "regeneration_limit_reached": regen_limit,
        "edit_limit_reached": edit_limit,
        # 상한에 하나라도 닿으면 승인할 때 '책임 승인' 사유가 필요하다.
        "approve_requires_reason": regen_limit or edit_limit,
    }


APPROVE_BLOCKING_RULES = ("S", "D")


def _blocking_rules(flags: list[dict]) -> list[str]:
    """'그대로 승인'을 막는 기준 중 지금 걸린 것."""
    hit = {flag.get("rule") for flag in flags}
    return [rule for rule in APPROVE_BLOCKING_RULES if rule in hit]


def allowed_actions(state: GraphState) -> list[str]:
    """지금 고를 수 있는 응답 목록."""
    limits = _limits(state)
    flags = state.get("validation_flags") or []
    actions = []
    # 그대로 게시하면 안 되는 문제가 있으면 '승인'을 막는다.
    # - S(출력 구조 오류): 깨진 결과를 게시할 수 없다.
    # - D(가격 불일치): 가격 표시 칸은 원본으로 바뀌지만 본문 속 틀린 가격 문구는 그대로 남는다.
    if not _blocking_rules(flags):
        actions.append("approve")
    if not limits["edit_limit_reached"]:
        actions.append("approve_with_edits")
    actions.append("reject")
    if not limits["regeneration_limit_reached"]:
        actions.append("reassess")
    return actions


def build_review_payload(state: GraphState) -> dict:
    """승인 화면에 보여 줄 정보를 모은다."""
    flags = state.get("validation_flags") or []
    product = state.get("product_input") or {}
    rules_hit = sorted({flag.get("rule", "") for flag in flags})
    return {
        "submission_id": state.get("submission_id"),
        "product": product,
        "content": state.get("generated_content"),
        "flags": flags,
        "rules_hit": [{"rule": r, "name": config.RULE_NAMES.get(r, r)} for r in rules_hit],
        # 화면은 '어떤 제목으로 등록되는지'를 앞에 붙이고, 여기서는 가격 안내만 준다.
        "approve_result_text": (
            f"가격은 AI가 쓴 값이 아니라 원본 값({price_display_from_product(product) or '가격 없음'})으로 표시됩니다."
        ),
        "allowed_actions": allowed_actions(state),
        "editable_fields": list(EDITABLE_FIELDS),
        "limits": _limits(state),
        "review_error": state.get("review_error"),
    }


def _clean_edits(edits) -> tuple[Optional[dict], Optional[str]]:
    """담당자 수정값을 검사·정리한다. (정리된 수정값, 오류 메시지)를 돌려준다."""
    if not isinstance(edits, dict) or not edits:
        return None, "수정할 내용을 입력해 주세요."
    unknown = [key for key in edits if key not in EDITABLE_FIELDS]
    if unknown:
        return None, f"수정할 수 없는 항목입니다: {', '.join(unknown)}"
    cleaned: dict = {}
    for key, value in edits.items():
        if key == "selling_points":
            # 목록이나 줄바꿈 글 모두 받는다.
            items = value.splitlines() if isinstance(value, str) else value
            if not isinstance(items, list):
                return None, "판매 포인트는 목록이나 줄바꿈 글로 입력해 주세요."
            points = [str(item).strip() for item in items if str(item).strip()]
            if not points:
                return None, "판매 포인트를 한 줄 이상 입력해 주세요."
            cleaned[key] = points
        else:
            text = str(value or "").strip()
            if not text:
                return None, f"'{key}' 항목이 비어 있습니다."
            cleaned[key] = text
    return cleaned, None


def check_review_response(state: GraphState, response) -> Optional[str]:
    """담당자 응답이 올바른지 검사한다. 문제가 있으면 한국어 오류 메시지를 돌려준다."""
    if not isinstance(response, dict):
        return "응답 형식이 올바르지 않습니다."
    action = response.get("action")
    if action not in ALL_ACTIONS:
        return f"알 수 없는 처리 방법입니다: {action}"
    # 글자 항목에 숫자 같은 다른 형식이 오면, 대기 건을 실패로 만들지 않고 다시 묻는다.
    for key in ("reason", "instructions", "reviewer"):
        if response.get(key) is not None and not isinstance(response.get(key), str):
            return f"'{key}' 항목은 글자로 입력해 주세요."
    limits = _limits(state)
    if action not in allowed_actions(state):
        if action == "reassess":
            return f"다시 판정은 최대 {config.MAX_REGENERATIONS}번까지 할 수 있습니다."
        if action == "approve_with_edits":
            return f"수정 후 승인은 최대 {config.MAX_EDIT_ROUNDS}번까지 할 수 있습니다."
        if "S" in _blocking_rules(state.get("validation_flags") or []):
            return "출력 구조 오류가 있어 그대로 승인할 수 없습니다. 수정하거나 다시 판정해 주세요."
        return "본문의 가격 문구가 원본과 달라 그대로 승인할 수 없습니다. 가격 문구를 고치거나 다시 판정해 주세요."
    reason = (response.get("reason") or "").strip()
    if action == "reject" and not reason:
        return "반려 사유를 입력해 주세요."
    if action == "approve" and limits["approve_requires_reason"] and not reason:
        return "반복 상한에 도달했습니다. 승인하려면 책임 승인 사유를 입력해 주세요."
    if action == "approve_with_edits":
        _, error = _clean_edits(response.get("edits"))
        return error
    return None


# ---------------------------------------------------------------------------
# 처리 단계
# ---------------------------------------------------------------------------

def prepare_product(state: GraphState) -> dict:
    """원본 상품 정보를 정리하고 처리 시작을 기록한다."""
    product = ProductInput.model_validate(state["product_input"]).model_dump()
    repository.update_submission(state["submission_id"], status="processing")
    repository.add_event(state["submission_id"], "submitted", "human", f"상품 {product['product_id']} 등록")
    return {
        "product_input": product,
        "status": "processing",
        "processing_route": "auto",
        "regeneration_count": state.get("regeneration_count", 0),
        "edit_round": state.get("edit_round", 0),
        "review_error": None,
    }


def _run_generation(state: GraphState, instructions: Optional[str], attempt: int) -> dict:
    """생성기를 부른다. 실패하면 오류 메시지를 상태에 담아 돌려준다."""
    try:
        content = generation.generate_content(
            state["product_input"],
            mode=state.get("generation_mode") or config.DEFAULT_GENERATION_MODE,
            sample_id=state.get("sample_id"),
            injection=state.get("injection"),
            instructions=instructions,
            attempt=attempt,
        )
    except generation.GenerationError as error:
        return {"generated_content": None, "error_message": str(error)}
    return {"generated_content": content, "error_message": None}


def generate_content(state: GraphState) -> dict:
    """상세페이지 콘텐츠를 처음 생성한다."""
    result = _run_generation(state, instructions=None, attempt=0)
    if result["error_message"]:
        repository.add_event(state["submission_id"], "generation_failed", "system", result["error_message"])
    else:
        repository.update_submission(state["submission_id"], generated_content=result["generated_content"])
        repository.add_event(state["submission_id"], "generated", "system", "콘텐츠 생성 완료")
    return result


def validate_content(state: GraphState) -> dict:
    """원본과 생성 콘텐츠를 비교해 승인 기준 위반을 찾는다."""
    flags = validation.validate(state["product_input"], state.get("generated_content"))
    passed = not flags
    repository.update_submission(state["submission_id"], validation_flags=flags)
    note = "검증 통과" if passed else f"문제 {len(flags)}건: {_rules_text(flags)}"
    repository.add_event(state["submission_id"], "validated", "system", note)
    return {"validation_flags": flags, "validation_passed": passed, "review_required": not passed}


def mark_pending(state: GraphState) -> dict:
    """승인 대기 상태로 저장한다(human_review 바로 앞에서 한 번만 실행)."""
    flags = state.get("validation_flags") or []
    repository.update_submission(
        state["submission_id"],
        status="pending_review",
        generated_content=state.get("generated_content"),
        regeneration_count=state.get("regeneration_count", 0),
        edit_round=state.get("edit_round", 0),
    )
    repository.add_event(state["submission_id"], "review_requested", "system", f"승인 필요: {_rules_text(flags)}")
    return {"status": "pending_review", "processing_route": "human", "review_error": None}


def human_review(state: GraphState) -> dict:
    """승인 담당자의 응답을 기다린다.

    interrupt()에서 그래프가 멈추고, Command(resume=응답)으로 다시 시작하면
    이 함수가 첫 줄부터 다시 실행되어 interrupt()가 응답을 돌려준다.
    그래서 여기서는 상태 값만 돌려주고 DB에는 아무것도 쓰지 않는다.
    """
    response = interrupt(build_review_payload(state))
    error = check_review_response(state, response)
    if error:
        return {"review_response": response if isinstance(response, dict) else None, "review_error": error}
    update: dict = {"review_response": response, "review_error": None}
    if response["action"] == "approve_with_edits":
        update["human_edits"], _ = _clean_edits(response.get("edits"))
    if response["action"] == "reassess":
        text = (response.get("instructions") or "").strip()
        update["reassessment_instructions"] = text or DEFAULT_REASSESS_INSTRUCTIONS
    return update


def record_review_error(state: GraphState) -> dict:
    """잘못된 응답을 기록한다. 그다음 다시 승인 대기로 돌아간다."""
    response = state.get("review_response") or {}
    note = _human_note(response, f"응답 거부: {state.get('review_error')}")
    repository.add_event(state["submission_id"], "review_invalid", "human", note)
    return {}


def apply_human_edits(state: GraphState) -> dict:
    """담당자 수정값을 콘텐츠에 반영한다. 반영 뒤 다시 검증한다."""
    content = dict(state.get("generated_content") or {})
    edits = state.get("human_edits") or {}
    content.update(edits)
    edit_round = state.get("edit_round", 0) + 1
    repository.update_submission(
        state["submission_id"], generated_content=content, edit_round=edit_round, last_action="approve_with_edits"
    )
    note = _human_note(state.get("review_response") or {}, f"수정 항목: {', '.join(edits)}")
    repository.add_event(state["submission_id"], "edited", "human", note)
    return {"generated_content": content, "edit_round": edit_round}


def regenerate_content(state: GraphState) -> dict:
    """담당자 지시를 넣어 콘텐츠를 다시 생성한다(다시 판정)."""
    instructions = state.get("reassessment_instructions") or DEFAULT_REASSESS_INSTRUCTIONS
    attempt = state.get("regeneration_count", 0) + 1
    submission_id = state["submission_id"]
    repository.update_submission(submission_id, regeneration_count=attempt, last_action="reassess")
    repository.add_event(
        submission_id, "reassess_requested", "human", _human_note(state.get("review_response") or {}, instructions)
    )
    result = _run_generation(state, instructions=instructions, attempt=attempt)
    if result["error_message"]:
        repository.add_event(submission_id, "generation_failed", "system", result["error_message"])
    else:
        repository.update_submission(submission_id, generated_content=result["generated_content"])
        repository.add_event(submission_id, "regenerated", "system", f"{attempt}번째 다시 생성 완료")
    return {**result, "regeneration_count": attempt}


def publish_to_demo_catalog(state: GraphState) -> dict:
    """데모 카탈로그에 게시한다. 같은 요청은 두 번 게시되지 않는다."""
    submission_id = state["submission_id"]
    product = state["product_input"]
    auto = state.get("processing_route", "auto") == "auto"
    response = state.get("review_response") or {}

    # 가격은 AI가 쓴 값을 버리고 원본 값으로만 채운다.
    final_content = dict(state.get("generated_content") or {})
    final_content["price_display"] = price_display_from_product(product)
    final_content["selling_price"] = product.get("selling_price")
    final_content["sale_price"] = product.get("sale_price")

    status = "auto_published" if auto else "approved_published"
    last_action = "auto" if auto else response.get("action", "approve")
    if not auto and response.get("action") == "approve":
        reason = (response.get("reason") or "").strip()
        repository.add_event(submission_id, "approved", "human", _human_note(response, reason or "승인"))

    created = repository.publish_to_catalog(submission_id, product, final_content, "auto" if auto else "human")
    repository.update_submission(submission_id, status=status, final_content=final_content, last_action=last_action)
    if created:
        repository.add_event(submission_id, "published", "system", "자동 게시" if auto else "승인 후 게시")
    return {"final_content": final_content, "status": status}


def reject_request(state: GraphState) -> dict:
    """반려한다. 카탈로그에는 게시하지 않는다."""
    response = state.get("review_response") or {}
    reason = (response.get("reason") or "").strip()
    repository.update_submission(
        state["submission_id"], status="rejected", rejection_reason=reason, last_action="reject"
    )
    repository.add_event(state["submission_id"], "rejected", "human", _human_note(response, reason))
    return {"status": "rejected", "rejection_reason": reason}


def mark_failed(state: GraphState) -> dict:
    """생성 실패를 기록한다. 실패한 요청은 절대 게시하지 않는다."""
    message = state.get("error_message") or "콘텐츠 생성에 실패했습니다."
    repository.update_submission(state["submission_id"], status="failed", error_message=message)
    repository.add_event(state["submission_id"], "failed", "system", message)
    return {"status": "failed"}


def finish(state: GraphState) -> dict:
    """마지막 단계. 최종 상태를 DB와 한 번 더 맞춘다(여러 번 실행해도 결과 같음)."""
    repository.update_submission(state["submission_id"], status=state.get("status", "failed"))
    return {}


# ---------------------------------------------------------------------------
# 분기 함수 (부수 효과 없음)
# ---------------------------------------------------------------------------

def route_after_generation(state: GraphState) -> str:
    return "mark_failed" if state.get("error_message") else "validate_content"


def route_after_validation(state: GraphState) -> str:
    return "publish_to_demo_catalog" if state.get("validation_passed") else "mark_pending"


def route_after_review(state: GraphState) -> str:
    if state.get("review_error"):
        return "record_review_error"
    action = (state.get("review_response") or {}).get("action")
    return {
        "approve": "publish_to_demo_catalog",
        "approve_with_edits": "apply_human_edits",
        "reassess": "regenerate_content",
        "reject": "reject_request",
    }[action]
