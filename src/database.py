"""업무 DB(SQLite) 연결과 테이블 만들기.

LangGraph 체크포인트 DB와는 별개의 파일이다.
- submissions: 요청 한 건의 현재 상태
- demo_catalog: 게시된 콘텐츠(데모 카탈로그)
- review_events: 요청마다 일어난 일의 기록(시스템·담당자)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from src import config

# 시간은 한국 시간(UTC+9) ISO-8601 문자열로 저장한다.
KST = timezone(timedelta(hours=9))

SCHEMA = """
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    thread_id TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT NOT NULL,
    product_id TEXT,
    product_name TEXT,
    generation_mode TEXT,
    sample_id TEXT,
    product_input_json TEXT,
    generated_content_json TEXT,
    validation_flags_json TEXT,
    final_content_json TEXT,
    last_action TEXT,
    rejection_reason TEXT,
    error_message TEXT,
    regeneration_count INTEGER NOT NULL DEFAULT 0,
    edit_round INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS demo_catalog (
    submission_id TEXT UNIQUE NOT NULL,
    product_id TEXT,
    product_name TEXT,
    final_content_json TEXT,
    published_at TEXT NOT NULL,
    publication_type TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason_or_note TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_submission ON review_events(submission_id);
"""


def now_iso() -> str:
    """현재 한국 시간을 ISO-8601 문자열로 돌려준다."""
    return datetime.now(KST).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    """저장된 시간 문자열을 datetime으로 바꾼다. 시간대가 없으면 한국 시간으로 본다."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed


def connect() -> sqlite3.Connection:
    """업무 DB에 연결한다. 테이블이 없으면 만든다.

    호출마다 짧게 연결하고 닫는 방식이라 화면의 여러 스레드에서 써도 안전하다.
    /mnt/c 같은 윈도우 드라이브에서는 WAL 모드가 실패할 수 있어 기본 저널을 쓴다.
    """
    conn = sqlite3.connect(config.app_db_path(), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
