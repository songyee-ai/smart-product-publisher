"""저장·복원 테스트: thread 분리, 재시작 후 복원, 지연 표시, human_review 재실행 무부작용."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta

from src import config, graph, repository
from src.database import KST, connect


def count_events(submission_id: str) -> int:
    return len(repository.list_events(submission_id))


def test_two_pending_requests_resume_independently(svc, submit_sample):
    first = submit_sample("S02")
    second = submit_sample("S07")
    assert first["thread_id"] != second["thread_id"]
    assert {row["submission_id"] for row in svc.list_pending()} == {first["submission_id"], second["submission_id"]}

    svc.respond(first["submission_id"], {"action": "approve", "reason": "확인"})

    assert svc.get_submission(first["submission_id"])["status"] == "approved_published"
    still = svc.get_submission(second["submission_id"])
    assert still["status"] == "pending_review"
    payload = svc.get_review_payload(second["submission_id"])
    assert payload["submission_id"] == second["submission_id"]
    assert any(flag["rule"] == "C" for flag in payload["flags"])

    svc.respond(second["submission_id"], {"action": "reject", "reason": "관리 방법 자료 필요"})
    assert svc.get_submission(second["submission_id"])["status"] == "rejected"
    assert [row["submission_id"] for row in svc.list_catalog()] == [first["submission_id"]]


def test_pending_review_survives_restart(svc, submit_sample):
    pending = submit_sample("S02")
    sid = pending["submission_id"]
    before = svc.get_review_payload(sid)

    # 앱 재시작 흉내: 체크포인트 연결을 끊고 새 SqliteSaver로 다시 연다.
    graph.reset_app_cache()

    assert [row["submission_id"] for row in svc.list_pending()] == [sid]
    after = svc.get_review_payload(sid)
    assert after == before
    assert graph.get_app().get_state(graph.thread_config(pending["thread_id"])).next == ("human_review",)

    result = svc.respond(sid, {"action": "approve", "reason": "재시작 뒤 승인"})
    assert result["status"] == "approved_published"
    assert repository.count_catalog(sid) == 1


def test_overdue_pending_is_flagged_and_sorted_first(svc, submit_sample):
    recent = submit_sample("S02")
    old = submit_sample("S07")
    backdated = (datetime.now(KST) - timedelta(days=config.OVERDUE_DAYS + 1)).isoformat(timespec="seconds")
    with closing(connect()) as conn, conn:
        conn.execute(
            "UPDATE submissions SET created_at = ? WHERE submission_id = ?", (backdated, old["submission_id"])
        )

    pending = svc.list_pending()

    assert [row["submission_id"] for row in pending] == [old["submission_id"], recent["submission_id"]]
    assert pending[0]["overdue"] is True
    assert pending[1]["overdue"] is False
    assert svc.dashboard_counts()["overdue"] == 1
    # 지연 건도 자동 승인하지 않는다.
    assert svc.get_submission(old["submission_id"])["status"] == "pending_review"


def test_human_review_reexecution_has_no_side_effects(svc, submit_sample):
    pending = submit_sample("S02")
    sid = pending["submission_id"]
    cfg = graph.thread_config(pending["thread_id"])
    app = graph.get_app()
    events_before = count_events(sid)

    # 응답 없이 다시 실행하면 human_review가 처음부터 다시 돌고 그대로 다시 멈춘다.
    app.invoke(None, cfg)
    app.invoke(None, cfg)

    assert count_events(sid) == events_before
    assert repository.count_catalog() == 0
    assert app.get_state(cfg).next == ("human_review",)

    # 잘못된 응답: 기록 한 줄(review_invalid)만 늘고 게시는 없다.
    svc.respond(sid, {"action": "reject"})
    assert count_events(sid) == events_before + 1
    assert repository.count_catalog() == 0

    # 올바른 응답: 승인 기록과 게시 기록이 한 번씩만 남는다.
    result = svc.respond(sid, {"action": "approve", "reason": "확인"})
    actions = [event["action"] for event in result["events"]]
    assert actions.count("approved") == 1
    assert actions.count("published") == 1
    assert actions.count("review_requested") == 1
    assert repository.count_catalog(sid) == 1


def test_publish_is_idempotent_by_submission_id(svc, submit_sample, sample_product):
    done = submit_sample("S01")
    product = sample_product("S01")

    created = repository.publish_to_catalog(done["submission_id"], product, done["final_content"], "auto")

    assert created is False
    assert repository.count_catalog() == 1


def test_history_and_catalog_listing(svc, submit_sample):
    auto = submit_sample("S01")
    pending = submit_sample("S02")

    history = svc.list_history()
    assert {row["submission_id"] for row in history} == {auto["submission_id"], pending["submission_id"]}
    assert [row["submission_id"] for row in svc.list_history("auto_published")] == [auto["submission_id"]]
    row = svc.get_submission(auto["submission_id"])
    for key in (
        "submission_id", "thread_id", "status", "created_at", "updated_at", "product_id", "product_name",
        "generation_mode", "sample_id", "product_input", "generated_content", "validation_flags",
        "final_content", "last_action", "rejection_reason", "error_message", "regeneration_count",
        "edit_round", "events", "overdue", "review_error",
    ):
        assert key in row
    assert row["sample_id"] == "S01"
    assert row["generation_mode"] == "sample"
