"""Streamlit 화면 스모크 테스트.

브라우저 없이 AppTest로 app.py를 실행해 화면 이동, 상품 등록, 승인 대기 흐름을 확인한다.
데이터는 매 테스트 임시 폴더에 만든다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ui.screens import EMPTY_PENDING_TEXT, PAGES

APP_PATH = Path(__file__).resolve().parent.parent / "app.py"
TIMEOUT = 120  # 그래프 실행이 들어가는 화면은 기본 3초보다 오래 걸릴 수 있다


@pytest.fixture
def app(tmp_path, monkeypatch):
    """임시 데이터 폴더를 쓰는 AppTest."""
    monkeypatch.setenv("SPP_DATA_DIR", str(tmp_path))
    from src import graph

    graph.reset_app_cache()
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.run()
    yield at
    graph.reset_app_cache()


def _assert_ok(at: AppTest) -> None:
    assert not at.exception, [e.value for e in at.exception]


def _go(at: AppTest, page: str) -> None:
    at.radio(key="nav").set_value(page).run()
    _assert_ok(at)


def _button(at: AppTest, label: str):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"'{label}' 버튼이 없습니다"
    return matches[0]


def _texts(at: AppTest) -> str:
    """화면에 나온 글자를 한데 모은다(마크다운·안내 상자·글자 요소)."""
    parts = [m.value for m in at.markdown]
    parts += [e.value for e in (*at.success, *at.warning, *at.info, *at.error, *at.caption)]
    parts += [t.value for t in at.text]
    return "\n".join(str(p) for p in parts)


def _submit_sample(at: AppTest, sample_id: str) -> None:
    """새 상품 등록 화면에서 샘플을 불러와 등록 요청한다."""
    _go(at, "새 상품 등록")
    at.selectbox(key="sample_pick").set_value(sample_id).run()
    at.button(key="fill_sample").click().run()
    _assert_ok(at)
    assert at.text_input(key="f_product_id").value
    _button(at, "등록 요청").click().run()
    _assert_ok(at)


def _first_sample(expected_review: bool) -> dict:
    """기본 묶음에서 사람 판단이 주어진 값인 첫 샘플."""
    from src.sample_data import list_samples

    return next(
        s for s in list_samples() if s.get("group") == "기본" and bool(s["expected_review"]) is expected_review
    )


def test_every_screen_renders(app):
    _assert_ok(app)
    for page in PAGES:
        _go(app, page)
        assert app.header[0].value == page
    _go(app, "승인 대기함")
    assert EMPTY_PENDING_TEXT in _texts(app)


def test_normal_sample_is_auto_published(app):
    sample = _first_sample(expected_review=False)
    _submit_sample(app, sample["sample_id"])
    assert any("자동 등록" in s.value for s in app.success)

    _go(app, "데모 카탈로그")
    texts = _texts(app)
    assert "자동 등록" in texts
    assert "등록 **1건**" in texts

    _go(app, "승인 대기함")
    assert EMPTY_PENDING_TEXT in _texts(app)


def test_risky_sample_goes_to_pending_and_can_be_rejected(app):
    sample = _first_sample(expected_review=True)
    _submit_sample(app, sample["sample_id"])
    assert any("승인 대기함" in w.value for w in app.warning)

    _go(app, "승인 대기함")
    assert "대기 중 **1건**" in _texts(app)

    # 대기함에서 상세 화면 열기
    _button(app, "상세 보기").click().run()
    _assert_ok(app)
    assert app.radio(key="nav").value == "승인 상세"
    assert any("승인하면 이 콘텐츠가 데모 카탈로그에" in i.value for i in app.info)

    # 반려: 사유가 비어 있으면 버튼이 막혀 있다
    action = next(r for r in app.radio if r.label == "처리 방법")
    action.set_value("reject").run()
    assert _button(app, "반려하기").disabled
    next(t for t in app.text_area if t.label == "반려 사유 (필수)").input("원본에 없는 기능 표현").run()
    assert not _button(app, "반려하기").disabled
    _button(app, "반려하기").click().run()
    _assert_ok(app)
    assert any("반려했습니다" in i.value for i in app.info)

    _go(app, "처리 이력")
    assert "반려" in _texts(app)


def test_risky_sample_can_be_approved(app):
    sample = _first_sample(expected_review=True)
    _submit_sample(app, sample["sample_id"])
    _go(app, "승인 상세")
    _button(app, "승인하기").click().run()
    _assert_ok(app)
    assert any("데모 카탈로그에 등록했습니다" in s.value for s in app.success)

    _go(app, "데모 카탈로그")
    assert "사람 승인" in _texts(app)


def test_ollama_unavailable_shows_korean_hint(app, monkeypatch):
    from src import config

    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:9")  # 아무도 듣지 않는 포트
    _go(app, "새 상품 등록")
    app.text_input(key="f_product_id").input("GH-TEST-001")
    app.text_input(key="f_product_name").input("테스트 차렵이불")
    app.radio(key="f_mode").set_value("ollama")
    _button(app, "등록 요청").click().run()
    _assert_ok(app)
    assert any("등록하지 않았습니다" in e.value for e in app.error)
    assert any("샘플 모드" in i.value for i in app.info)


def test_sample_batch_from_dashboard(app):
    _go(app, "대시보드")
    _button(app, "샘플 전체 실행").click().run()
    _assert_ok(app)
    assert any("샘플" in s.value and "처리했습니다" in s.value for s in app.success)
    pending_metric = next(m for m in app.metric if m.label == "승인 대기")
    assert int(pending_metric.value) > 0
