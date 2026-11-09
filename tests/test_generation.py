"""콘텐츠 생성(sample 모드·ollama 모드) 테스트. ollama는 httpx를 가짜로 바꿔 서버 없이 검사한다."""
from __future__ import annotations

import json

import httpx
import pytest

from src import config, generation
from src.generation import (
    INJECTIONS,
    GenerationError,
    LLMResponseError,
    LLMUnavailableError,
    build_clean_content,
    generate_content,
    injection_options,
)
from src.sample_data import SAMPLES, get_sample, list_samples
from src.schemas import GeneratedContent, ProductInput
from src.validation import validate


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPP_DATA_DIR", str(tmp_path))


@pytest.fixture
def product() -> dict:
    return get_sample("S01")["product"]


# ------------------------------------------------------------------ 샘플 데이터
def test_samples_shape():
    assert 18 <= len(SAMPLES) <= 20
    ids = [s["sample_id"] for s in SAMPLES]
    assert len(ids) == len(set(ids))
    for sample in SAMPLES:
        assert set(sample) >= {"sample_id", "title", "product", "content_patch", "expected_review",
                               "expected_reason", "group"}
        assert sample["group"] in ("기본", "함정")
        assert isinstance(sample["expected_review"], bool)
        ProductInput.model_validate(sample["product"])
        assert "굿홈앤리빙" in sample["product"]["product_name"]


def test_samples_have_both_groups_and_labels():
    groups = {s["group"] for s in SAMPLES}
    assert groups == {"기본", "함정"}
    traps = [s for s in SAMPLES if s["group"] == "함정"]
    assert any(s["expected_review"] for s in traps)
    assert any(not s["expected_review"] for s in traps)


def test_get_sample_returns_copy_and_unknown_raises():
    sample = get_sample("S02")
    sample["product"]["material"] = "변경"
    assert get_sample("S02")["product"]["material"] != "변경"
    assert len(list_samples()) == len(SAMPLES)
    with pytest.raises(KeyError):
        get_sample("S99")


# ------------------------------------------------------------------ sample 모드
def test_clean_template_uses_only_source_fields(product):
    content = build_clean_content(product)
    GeneratedContent.model_validate(content)
    assert content["care_guide"] == product["care_instructions"]
    assert content["price_display"] == "정상가 79,000원 → 할인가 59,000원"
    for claim in content["fact_claims"]:
        assert claim["source_field"]
        assert claim["source_value"]


def test_clean_template_never_invents_facts_for_any_sample():
    for sample in SAMPLES:
        content = build_clean_content(sample["product"])
        GeneratedContent.model_validate(content)
        assert validate(sample["product"], content, rules=["A", "B", "D"]) == [], sample["sample_id"]


def test_clean_template_empty_fields():
    bare = {"product_id": "X", "product_name": "굿홈앤리빙 무명 쿠션", "category": "생활용품"}
    content = build_clean_content(bare)
    GeneratedContent.model_validate(content)
    assert content["care_guide"] == ""
    assert content["price_display"] is None


def test_price_display_single_price():
    item = {"product_id": "X", "product_name": "굿홈앤리빙 쿠션", "selling_price": 15000}
    assert build_clean_content(item)["price_display"] == "15,000원"


def test_sample_mode_is_deterministic():
    for sample in SAMPLES:
        first = generate_content(sample["product"], mode="sample", sample_id=sample["sample_id"])
        second = generate_content(sample["product"], mode="sample", sample_id=sample["sample_id"])
        assert first == second


def test_sample_patch_applied():
    sample = get_sample("S02")
    content = generate_content(sample["product"], mode="sample", sample_id="S02")
    assert "극세사" in content["detail_description"]
    assert content["one_line_summary"] == "포근한 극세사 차렵이불"


def test_patch_placeholder_filled():
    sample = get_sample("S14")
    content = generate_content(sample["product"], mode="sample", sample_id="S14")
    assert content["one_line_summary"] == f"순면으로 만든 {sample['product']['product_name']}"


def test_reassess_instructions_return_clean_template():
    sample = get_sample("S03")
    content = generate_content(sample["product"], mode="sample", sample_id="S03",
                               instructions="원본 자료만 사용해 다시 작성")
    assert content == build_clean_content(sample["product"])
    assert validate(sample["product"], content) == []


@pytest.mark.parametrize("key, rule", [
    ("material", "A"), ("antibacterial", "B"), ("waterproof", "B"), ("price", "D"), ("size", "A"),
])
def test_injections_trigger_expected_rule(product, key, rule):
    content = generate_content(product, mode="sample", injection=key)
    assert rule in {flag["rule"] for flag in validate(product, content)}


def test_injection_none_and_options(product):
    assert generate_content(product, mode="sample", injection="none") == build_clean_content(product)
    options = injection_options()
    assert [key for key, _ in options] == list(INJECTIONS)
    assert dict(options)["material"] == "소재를 극세사로 바꿔 씀"


def test_unknown_mode_injection_sample(product):
    with pytest.raises(GenerationError):
        generate_content(product, mode="foo")
    with pytest.raises(GenerationError):
        generate_content(product, mode="sample", injection="foo")
    with pytest.raises(GenerationError):
        generate_content(product, mode="sample", sample_id="S99")


# ------------------------------------------------------------------ ollama 모드
class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("JSON 아님")
        return self._payload


def ollama_reply(content_text: str) -> FakeResponse:
    return FakeResponse(payload={"message": {"role": "assistant", "content": content_text}})


def test_ollama_success_request_body(monkeypatch, product):
    captured = {}
    good = build_clean_content(product)

    def fake_post(url, **kwargs):
        captured.update(url=url, body=kwargs["json"], timeout=kwargs["timeout"])
        return ollama_reply("<think>생각 중</think>\n" + json.dumps(good, ensure_ascii=False))

    monkeypatch.setattr(generation.httpx, "post", fake_post)
    result = generate_content(product, mode="ollama", instructions="가격 문구를 빼 주세요")
    assert result == GeneratedContent.model_validate(good).model_dump()
    body = captured["body"]
    assert captured["url"] == f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    assert captured["timeout"] == config.OLLAMA_TIMEOUT_SECONDS
    assert body["model"] == config.OLLAMA_MODEL
    assert body["stream"] is False and body["think"] is False
    assert body["options"]["temperature"] == 0.3
    assert body["format"] == GeneratedContent.model_json_schema()
    assert "가격 문구를 빼 주세요" in body["messages"][-1]["content"]
    assert body["messages"][0]["role"] == "system"


def test_ollama_code_fence_stripped(monkeypatch, product):
    good = build_clean_content(product)
    text = "```json\n" + json.dumps(good, ensure_ascii=False) + "\n```"
    monkeypatch.setattr(generation.httpx, "post", lambda *a, **k: ollama_reply(text))
    assert generate_content(product, mode="ollama")["display_title"] == good["display_title"]


def test_ollama_injection_applied(monkeypatch, product):
    good = build_clean_content(product)
    monkeypatch.setattr(generation.httpx, "post",
                        lambda *a, **k: ollama_reply(json.dumps(good, ensure_ascii=False)))
    content = generate_content(product, mode="ollama", injection="antibacterial")
    assert "항균" in content["detail_description"]


def test_ollama_connection_error(monkeypatch, product):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("연결 거부")

    monkeypatch.setattr(generation.httpx, "post", boom)
    with pytest.raises(LLMUnavailableError, match="Ollama 서버에 연결할 수 없습니다"):
        generate_content(product, mode="ollama")


def test_ollama_timeout(monkeypatch, product):
    def slow(*args, **kwargs):
        raise httpx.ReadTimeout("시간 초과")

    monkeypatch.setattr(generation.httpx, "post", slow)
    with pytest.raises(LLMUnavailableError):
        generate_content(product, mode="ollama")


def test_ollama_http_error_status(monkeypatch, product):
    monkeypatch.setattr(generation.httpx, "post", lambda *a, **k: FakeResponse(status_code=404, payload={}))
    with pytest.raises(LLMUnavailableError):
        generate_content(product, mode="ollama")


@pytest.mark.parametrize("text", ["이건 JSON이 아닙니다", '{"display_title": "제목만"}', "<think>…</think>"])
def test_ollama_bad_response(monkeypatch, product, text):
    monkeypatch.setattr(generation.httpx, "post", lambda *a, **k: ollama_reply(text))
    with pytest.raises(LLMResponseError):
        generate_content(product, mode="ollama")


def test_ollama_missing_message_field(monkeypatch, product):
    monkeypatch.setattr(generation.httpx, "post", lambda *a, **k: FakeResponse(payload={"done": True}))
    with pytest.raises(LLMResponseError):
        generate_content(product, mode="ollama")


def test_error_hierarchy():
    assert issubclass(LLMUnavailableError, GenerationError)
    assert issubclass(LLMResponseError, GenerationError)
