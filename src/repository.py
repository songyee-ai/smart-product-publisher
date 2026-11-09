"""업무 DB 읽기·쓰기 함수 모음.

그래프 단계 함수와 서비스는 SQL을 직접 쓰지 않고 이 함수들을 부른다.
목록·딕셔너리 값은 JSON 문자열로 저장하고, 읽을 때 다시 파이썬 값으로 바꾼다.
"""
from __future__ import annotations

import json
from contextlib import closing
from typing import Any, Optional

from src.database import connect, now_iso

# 파이썬 값 ↔ JSON 문자열로 바꿔 저장하는 칼럼 (state 키 → DB 칼럼)
JSON_FIELDS = {
    "product_input": "product_input_json",
    "generated_content": "generated_content_json",
    "validation_flags": "validation_flags_json",
    "final_content": "final_content_json",
}

# 그대로 저장하는 칼럼
PLAIN_FIELDS = {
    "status",
    "product_id",
    "product_name",
    "generation_mode",
    "sample_id",
    "last_action",
    "rejection_reason",
    "error_message",
    "regeneration_count",
    "edit_round",
    "created_at",
}


def _dumps(value: Any) -> Optional[str]:
    """None은 그대로 두고, 나머지는 한글이 보이는 JSON 문자열로 바꾼다."""
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(text: Optional[str]) -> Any:
    if text is None or text == "":
        return None
    return json.loads(text)


def create_submission(
    submission_id: str,
    thread_id: str,
    product: dict,
    generation_mode: str,
    sample_id: Optional[str],
) -> None:
    """새 요청을 '처리 중' 상태로 저장한다."""
    now = now_iso()
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO submissions (
                submission_id, thread_id, created_at, updated_at, status,
                product_id, product_name, generation_mode, sample_id,
                product_input_json, validation_flags_json
            ) VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, '[]')
            """,
            (
                submission_id,
                thread_id,
                now,
                now,
                product.get("product_id"),
                product.get("product_name"),
                generation_mode,
                sample_id,
                _dumps(product),
            ),
        )


def submission_exists(submission_id: str) -> bool:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT 1 FROM submissions WHERE submission_id = ?", (submission_id,)
        ).fetchone()
    return row is not None


def update_submission(submission_id: str, **fields: Any) -> None:
    """요청 한 건의 칼럼을 고친다. updated_at은 항상 현재 시간으로 바뀐다.

    같은 값으로 여러 번 불러도 결과가 같다(멱등).
    """
    columns: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key in JSON_FIELDS:
            columns.append(f"{JSON_FIELDS[key]} = ?")
            values.append(_dumps(value))
        elif key in PLAIN_FIELDS:
            columns.append(f"{key} = ?")
            values.append(value)
        else:
            raise KeyError(f"저장할 수 없는 필드입니다: {key}")
    columns.append("updated_at = ?")
    values.append(now_iso())
    values.append(submission_id)
    with closing(connect()) as conn, conn:
        conn.execute(
            f"UPDATE submissions SET {', '.join(columns)} WHERE submission_id = ?",
            values,
        )


def add_event(submission_id: str, action: str, actor: str, note: str = "") -> None:
    """처리 기록 한 줄을 남긴다. actor는 'system' 또는 'human'."""
    with closing(connect()) as conn, conn:
        conn.execute(
            """
            INSERT INTO review_events (submission_id, action, actor, reason_or_note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (submission_id, action, actor, note, now_iso()),
        )


def list_events(submission_id: str) -> list[dict]:
    with closing(connect()) as conn:
        rows = conn.execute(
            """
            SELECT action, actor, reason_or_note, created_at FROM review_events
            WHERE submission_id = ? ORDER BY event_id
            """,
            (submission_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def publish_to_catalog(
    submission_id: str,
    product: dict,
    final_content: dict,
    publication_type: str,
) -> bool:
    """데모 카탈로그에 게시한다. 이미 게시된 요청이면 아무것도 하지 않는다.

    submission_id가 UNIQUE라서 INSERT OR IGNORE로 중복 게시를 막는다.
    새로 게시했으면 True, 이미 있었으면 False를 돌려준다.
    """
    with closing(connect()) as conn, conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO demo_catalog (
                submission_id, product_id, product_name, final_content_json,
                published_at, publication_type
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                submission_id,
                product.get("product_id"),
                product.get("product_name"),
                _dumps(final_content),
                now_iso(),
                publication_type,
            ),
        )
        return cursor.rowcount == 1


def _row_to_submission(row) -> dict:
    """DB 행을 화면에서 쓰는 딕셔너리로 바꾼다(JSON 칼럼은 파싱)."""
    data = dict(row)
    for key, column in JSON_FIELDS.items():
        data[key] = _loads(data.pop(column))
    if data["validation_flags"] is None:
        data["validation_flags"] = []
    return data


def get_submission_row(submission_id: str) -> Optional[dict]:
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT * FROM submissions WHERE submission_id = ?", (submission_id,)
        ).fetchone()
    return _row_to_submission(row) if row else None


def list_submission_rows(status: Optional[str] = None) -> list[dict]:
    """요청 목록을 최신순으로 돌려준다. status를 주면 그 상태만."""
    sql = "SELECT * FROM submissions"
    params: tuple = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY created_at DESC, submission_id DESC"
    with closing(connect()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_submission(row) for row in rows]


def list_catalog_rows() -> list[dict]:
    """데모 카탈로그를 최근 게시순으로 돌려준다."""
    with closing(connect()) as conn:
        rows = conn.execute(
            "SELECT * FROM demo_catalog ORDER BY published_at DESC, rowid DESC"
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["final_content"] = _loads(data.pop("final_content_json"))
        result.append(data)
    return result


def count_catalog(submission_id: Optional[str] = None) -> int:
    """카탈로그 행 수. submission_id를 주면 그 요청의 게시 행 수."""
    sql = "SELECT COUNT(*) FROM demo_catalog"
    params: tuple = ()
    if submission_id:
        sql += " WHERE submission_id = ?"
        params = (submission_id,)
    with closing(connect()) as conn:
        return conn.execute(sql, params).fetchone()[0]
