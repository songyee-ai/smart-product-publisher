"""그래프 흐름 테스트: 자동 게시, 승인 대기, 담당자 응답 네 가지와 반복 상한."""
from __future__ import annotations

import pytest

from src import config, generation, repository
from src.nodes import EDITABLE_FIELDS


def actions_of(submission: dict) -> list[str]:
    return [event["action"] for event in submission["events"]]


def clean_edits(product: dict) -> dict:
    """원본만으로 만든 깨끗한 문구로 고칠 수 있는 네 항목을 채운다."""
    clean = generation.generate_content(product, mode="sample")
    return {field: clean[field] for field in EDITABLE_FIELDS}


def test_normal_product_is_auto_published(svc, submit_sample, sample_product):
    result = submit_sample("S01")

    assert result["status"] == "auto_published"
    assert result["validation_flags"] == []
    assert result["last_action"] == "auto"
    catalog = svc.list_catalog()
    assert [row["submission_id"] for row in catalog] == [result["submission_id"]]
    assert catalog[0]["publication_type"] == "auto"
    # 게시 가격은 원본 값에서만 온다.
    product = sample_product("S01")
    assert result["final_content"]["selling_price"] == product["selling_price"]
    assert result["final_content"]["sale_price"] == product["sale_price"]
    assert actions_of(result) == ["submitted", "generated", "validated", "published"]
    assert svc.get_review_payload(result["submission_id"]) is None


def test_mismatch_goes_to_pending_review(svc, submit_sample):
    result = submit_sample("S02")

    assert result["status"] == "pending_review"
    assert any(flag["rule"] == "A" for flag in result["validation_flags"])
    assert svc.list_catalog() == []
    assert actions_of(result)[-1] == "review_requested"
    payload = svc.get_review_payload(result["submission_id"])
    assert payload["submission_id"] == result["submission_id"]
    assert "A" in [item["rule"] for item in payload["rules_hit"]]
    assert set(payload["allowed_actions"]) == {"approve", "approve_with_edits", "reject", "reassess"}
    assert payload["review_error"] is None


def test_approve_publishes_to_catalog(svc, submit_sample):
    pending = submit_sample("S02")

    result = svc.respond(pending["submission_id"], {"action": "approve", "reason": "표현 확인함", "reviewer": "김담당"})

    assert result["status"] == "approved_published"
    assert result["last_action"] == "approve"
    catalog = svc.list_catalog()
    assert len(catalog) == 1
    assert catalog[0]["publication_type"] == "human"
    approved = [e for e in result["events"] if e["action"] == "approved"]
    assert approved[0]["actor"] == "human"
    assert "김담당" in approved[0]["reason_or_note"]
    assert actions_of(result)[-1] == "published"


def test_edits_that_fix_problem_publish_edited_text(svc, submit_sample, sample_product):
    pending = submit_sample("S02")
    edits = clean_edits(sample_product("S02"))
    edits["display_title"] = edits["display_title"] + " (담당자 수정)"

    result = svc.respond(pending["submission_id"], {"action": "approve_with_edits", "edits": edits})

    assert result["status"] == "approved_published"
    assert result["edit_round"] == 1
    assert result["final_content"]["display_title"].endswith("(담당자 수정)")
    assert svc.list_catalog()[0]["final_content"]["display_title"].endswith("(담당자 수정)")
    assert "edited" in actions_of(result)


def test_edits_that_keep_problem_return_to_pending(svc, submit_sample):
    pending = submit_sample("S02")

    result = svc.respond(
        pending["submission_id"],
        {"action": "approve_with_edits", "edits": {"one_line_summary": "포근한 촉감의 침구"}},
    )

    assert result["status"] == "pending_review"
    assert result["edit_round"] == 1
    assert result["review_error"] is None
    assert svc.list_catalog() == []
    payload = svc.get_review_payload(pending["submission_id"])
    assert payload["content"]["one_line_summary"] == "포근한 촉감의 침구"
    assert payload["limits"]["edit_round"] == 1


def test_selling_points_accept_newline_text(svc, submit_sample):
    pending = submit_sample("S02")

    svc.respond(
        pending["submission_id"],
        {"action": "approve_with_edits", "edits": {"selling_points": "첫째 장점\n\n둘째 장점"}},
    )

    payload = svc.get_review_payload(pending["submission_id"])
    assert payload["content"]["selling_points"] == ["첫째 장점", "둘째 장점"]


def test_edits_on_other_fields_are_refused(svc, submit_sample):
    pending = submit_sample("S02")

    result = svc.respond(
        pending["submission_id"],
        {"action": "approve_with_edits", "edits": {"price_display": "10,000원"}},
    )

    assert result["status"] == "pending_review"
    assert "수정할 수 없는 항목" in result["review_error"]
    assert result["edit_round"] == 0


def test_reject_without_reason_stays_pending(svc, submit_sample):
    pending = submit_sample("S02")

    result = svc.respond(pending["submission_id"], {"action": "reject", "reason": "  "})

    assert result["status"] == "pending_review"
    assert result["review_error"] == "반려 사유를 입력해 주세요."
    assert actions_of(result)[-1] == "review_invalid"
    assert svc.get_review_payload(pending["submission_id"])["review_error"] == "반려 사유를 입력해 주세요."


def test_unknown_action_stays_pending(svc, submit_sample):
    pending = submit_sample("S02")

    result = svc.respond(pending["submission_id"], {"action": "delete"})

    assert result["status"] == "pending_review"
    assert "알 수 없는 처리 방법" in result["review_error"]


def test_reject_with_reason(svc, submit_sample):
    pending = submit_sample("S02")
    svc.respond(pending["submission_id"], {"action": "reject"})  # 사유 없음 → 다시 대기

    result = svc.respond(pending["submission_id"], {"action": "reject", "reason": "소재 표기가 원본과 다름"})

    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "소재 표기가 원본과 다름"
    assert result["review_error"] is None
    assert svc.list_catalog() == []
    assert actions_of(result)[-1] == "rejected"


def test_reassess_regenerates_clean_content_and_publishes(svc, submit_sample):
    """다시 판정으로 깨끗한 콘텐츠가 나오면 사람이 거친 건이므로 approved_published로 게시한다."""
    pending = submit_sample("S02")

    result = svc.respond(
        pending["submission_id"], {"action": "reassess", "instructions": "원본 소재만 써 주세요"}
    )

    assert result["status"] == "approved_published"
    assert result["last_action"] == "reassess"
    assert result["regeneration_count"] == 1
    assert result["validation_flags"] == []
    assert len(svc.list_catalog()) == 1
    actions = actions_of(result)
    assert actions.index("reassess_requested") < actions.index("regenerated") < actions.index("published")


def test_regeneration_limit(svc, submit_sample):
    """관리 방법이 원본에 없으면 다시 생성해도 남는다 → 상한 도달 후 다시 판정 거부, 책임 승인만 가능."""
    pending = submit_sample("S07")
    sid = pending["submission_id"]
    assert pending["status"] == "pending_review"

    for attempt in range(1, config.MAX_REGENERATIONS + 1):
        result = svc.respond(sid, {"action": "reassess", "instructions": "원본만 사용"})
        assert result["status"] == "pending_review"
        assert result["regeneration_count"] == attempt

    payload = svc.get_review_payload(sid)
    assert "reassess" not in payload["allowed_actions"]
    assert payload["limits"]["approve_requires_reason"] is True

    refused = svc.respond(sid, {"action": "reassess", "instructions": "한 번 더"})
    assert refused["status"] == "pending_review"
    assert "최대" in refused["review_error"]
    assert refused["regeneration_count"] == config.MAX_REGENERATIONS

    no_reason = svc.respond(sid, {"action": "approve"})
    assert no_reason["status"] == "pending_review"
    assert "책임 승인" in no_reason["review_error"]

    approved = svc.respond(sid, {"action": "approve", "reason": "관리 방법은 별도 안내문으로 제공"})
    assert approved["status"] == "approved_published"
    assert len(svc.list_catalog()) == 1


def test_edit_limit(svc, submit_sample):
    pending = submit_sample("S02")
    sid = pending["submission_id"]
    for _ in range(config.MAX_EDIT_ROUNDS):
        svc.respond(sid, {"action": "approve_with_edits", "edits": {"one_line_summary": "부드러운 침구"}})

    payload = svc.get_review_payload(sid)
    assert payload["limits"]["edit_round"] == config.MAX_EDIT_ROUNDS
    assert "approve_with_edits" not in payload["allowed_actions"]
    refused = svc.respond(sid, {"action": "approve_with_edits", "edits": {"one_line_summary": "다시"}})
    assert "최대" in refused["review_error"]


def test_double_respond_raises_and_publishes_once(svc, submit_sample):
    pending = submit_sample("S02")
    sid = pending["submission_id"]
    svc.respond(sid, {"action": "approve", "reason": "확인"})

    with pytest.raises(ValueError, match="이미 처리된 요청입니다"):
        svc.respond(sid, {"action": "approve", "reason": "또 확인"})

    assert repository.count_catalog(sid) == 1
    assert svc.get_submission(sid)["status"] == "approved_published"


def test_respond_on_auto_published_raises(svc, submit_sample):
    done = submit_sample("S01")
    with pytest.raises(ValueError, match="이미 처리된 요청입니다"):
        svc.respond(done["submission_id"], {"action": "approve"})


def test_generation_error_marks_failed(svc, sample_product, monkeypatch):
    def broken(*args, **kwargs):
        raise generation.LLMUnavailableError("Ollama 서버에 연결할 수 없습니다")

    monkeypatch.setattr(generation, "generate_content", broken)

    result = svc.submit_product(sample_product("S01"), mode="ollama")

    assert result["status"] == "failed"
    assert "Ollama" in result["error_message"]
    assert svc.list_catalog() == []
    assert actions_of(result)[-2:] == ["generation_failed", "failed"]


def test_bad_product_input_raises_before_graph(svc):
    with pytest.raises(ValueError, match="상품명"):
        svc.submit_product({"product_id": "P-1", "product_name": ""})
    assert svc.list_history() == []


def test_dashboard_counts(svc, submit_sample):
    submit_sample("S01")
    pending = submit_sample("S02")
    svc.respond(pending["submission_id"], {"action": "reject", "reason": "반려"})
    submit_sample("S07")

    counts = svc.dashboard_counts()

    assert counts["total"] == 3
    assert counts["auto_published"] == 1
    assert counts["rejected"] == 1
    assert counts["pending_review"] == 1
    assert counts["overdue"] == 0


def test_price_mismatch_cannot_be_approved_as_is(svc, submit_sample):
    """D(가격 불일치)는 본문의 틀린 가격이 남으므로 그대로 승인할 수 없다."""
    sub = submit_sample("S06")
    payload = svc.get_review_payload(sub["submission_id"])
    assert "approve" not in payload["allowed_actions"]
    result = svc.respond(sub["submission_id"], {"action": "approve"})
    assert result["status"] == "pending_review"
    assert "가격" in result["review_error"]
    assert svc.list_catalog() == []


def test_non_text_reason_keeps_item_pending(svc, submit_sample):
    """사유 칸에 글자가 아닌 값이 와도 대기 건이 실패로 바뀌지 않는다."""
    sub = submit_sample("S02")
    result = svc.respond(sub["submission_id"], {"action": "reject", "reason": 123})
    assert result["status"] == "pending_review"
    assert "글자" in result["review_error"]
    final = svc.respond(sub["submission_id"], {"action": "reject", "reason": "문구 확인 필요"})
    assert final["status"] == "rejected"
