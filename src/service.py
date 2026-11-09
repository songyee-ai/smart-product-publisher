"""화면(UI)이 부르는 유일한 업무 함수 모음.

- submit_product: 상품을 등록하고 그래프를 실행한다.
- respond: 승인 대기 중인 요청에 담당자 응답을 넣어 그래프를 이어서 실행한다.
- 조회 함수: 요청·대기함·이력·카탈로그·대시보드 숫자.
"""
from __future__ import annotations

import secrets
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from langgraph.types import Command
from pydantic import ValidationError

from src import config, repository, sample_data
from src.database import KST, parse_iso
from src.graph import get_app, thread_config
from src.schemas import ProductInput

# 같은 요청에 응답이 동시에 두 번 들어오는 것을 막는다(버튼 두 번 클릭 등).
_respond_lock = threading.Lock()


def _new_submission_id() -> str:
    """'SUB-YYYYMMDD-HHMMSS-xxxx' 형식의 요청 번호를 만든다(겹치면 다시 만든다)."""
    while True:
        stamp = datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        submission_id = f"SUB-{stamp}-{secrets.token_hex(2).upper()}"
        if not repository.submission_exists(submission_id):
            return submission_id


def _validation_message(error: ValidationError) -> str:
    """pydantic 오류를 담당자가 읽을 수 있는 한국어 문장으로 바꾼다."""
    names = {"product_id": "상품 코드", "product_name": "상품명"}
    fields = []
    for item in error.errors():
        field = str(item["loc"][0]) if item.get("loc") else "입력값"
        fields.append(names.get(field, field))
    return f"상품 정보를 확인해 주세요: {', '.join(dict.fromkeys(fields))} 항목이 비어 있거나 형식이 맞지 않습니다."


def _is_overdue(row: dict) -> bool:
    """승인 대기가 OVERDUE_DAYS일을 넘었는지 본다."""
    if row.get("status") != "pending_review":
        return False
    age = datetime.now(KST) - parse_iso(row["created_at"])
    return age > timedelta(days=config.OVERDUE_DAYS)


def _pending_payload(thread_id: str) -> Optional[dict]:
    """체크포인터에서 멈춘 지점(interrupt)의 승인 화면 정보를 읽는다."""
    snapshot = get_app().get_state(thread_config(thread_id))
    payload = None
    for task in snapshot.tasks:
        if task.interrupts:
            payload = task.interrupts[0].value
    return payload


def _decorate(row: dict, with_review_error: bool = True) -> dict:
    """DB 행에 기록 목록·지연 여부·응답 오류를 붙인다."""
    row["events"] = repository.list_events(row["submission_id"])
    row["overdue"] = _is_overdue(row)
    row["review_error"] = None
    if with_review_error and row["status"] == "pending_review":
        payload = _pending_payload(row["thread_id"]) or {}
        row["review_error"] = payload.get("review_error")
    return row


def _mark_crashed(submission_id: str, error: Exception) -> None:
    """예상하지 못한 오류로 그래프가 멈추면 실패로 기록한다(게시하지 않는다)."""
    message = f"처리 중 오류가 발생했습니다: {error}"
    repository.update_submission(submission_id, status="failed", error_message=message)
    repository.add_event(submission_id, "failed", "system", message)


def submit_product(
    product: dict,
    *,
    mode: str = "sample",
    sample_id: Optional[str] = None,
    injection: Optional[str] = None,
) -> dict:
    """상품을 등록하고 생성→검증→(게시 또는 승인 대기)까지 실행한다."""
    try:
        clean = ProductInput.model_validate(product).model_dump()
    except ValidationError as error:
        raise ValueError(_validation_message(error)) from error
    if mode not in ("sample", "ollama"):
        raise ValueError(f"알 수 없는 생성 방식입니다: {mode}")

    submission_id = _new_submission_id()
    thread_id = uuid.uuid4().hex
    repository.create_submission(submission_id, thread_id, clean, mode, sample_id)
    state = {
        "submission_id": submission_id,
        "thread_id": thread_id,
        "product_input": clean,
        "generation_mode": mode,
        "sample_id": sample_id,
        "injection": injection,
        "regeneration_count": 0,
        "edit_round": 0,
    }
    try:
        get_app().invoke(state, thread_config(thread_id))
    except Exception as error:  # 화면이 멈추지 않도록 실패로 기록하고 결과를 돌려준다.
        _mark_crashed(submission_id, error)
    return get_submission(submission_id)


def respond(submission_id: str, response: dict) -> dict:
    """승인 대기 요청에 담당자 응답을 넣고 그래프를 이어서 실행한다."""
    with _respond_lock:
        row = repository.get_submission_row(submission_id)
        if row is None:
            raise ValueError("요청을 찾을 수 없습니다")
        # 이미 끝난 thread에 resume을 보내면 조용히 무시되므로 DB 상태로 먼저 막는다.
        if row["status"] != "pending_review":
            raise ValueError("이미 처리된 요청입니다")
        try:
            get_app().invoke(Command(resume=response), thread_config(row["thread_id"]))
        except Exception as error:
            _mark_crashed(submission_id, error)
    return get_submission(submission_id)


def get_submission(submission_id: str) -> Optional[dict]:
    row = repository.get_submission_row(submission_id)
    return _decorate(row) if row else None


def get_review_payload(submission_id: str) -> Optional[dict]:
    """승인 화면 정보. DB가 아니라 체크포인터에서 읽어 '멈춘 지점 복원'을 보여 준다."""
    row = repository.get_submission_row(submission_id)
    if row is None or row["status"] != "pending_review":
        return None
    return _pending_payload(row["thread_id"])


def list_pending() -> list[dict]:
    """승인 대기함: 지연 건 먼저, 그다음 오래된 순."""
    rows = [_decorate(row) for row in repository.list_submission_rows("pending_review")]
    return sorted(rows, key=lambda row: (not row["overdue"], row["created_at"]))


def list_history(status: Optional[str] = None) -> list[dict]:
    """전체 처리 이력(최신순). status를 주면 그 상태만."""
    return [_decorate(row) for row in repository.list_submission_rows(status)]


def list_catalog() -> list[dict]:
    return repository.list_catalog_rows()


def dashboard_counts() -> dict:
    """대시보드 숫자: 전체·상태별·지연 건수."""
    rows = repository.list_submission_rows()
    counts = {
        "total": len(rows),
        "auto_published": 0,
        "pending_review": 0,
        "approved_published": 0,
        "rejected": 0,
        "failed": 0,
        "overdue": 0,
    }
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] += 1
        if _is_overdue(row):
            counts["overdue"] += 1
    return counts


def run_sample_batch(sample_ids: Optional[list[str]] = None) -> list[dict]:
    """고정 샘플을 샘플 모드로 차례대로 실행한다."""
    if sample_ids is None:
        sample_ids = [sample["sample_id"] for sample in sample_data.SAMPLES]
    results = []
    for sample_id in sample_ids:
        sample = sample_data.get_sample(sample_id)
        results.append(submit_product(sample["product"], mode="sample", sample_id=sample_id))
    return results
