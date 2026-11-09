"""상세페이지 콘텐츠 생성.

- sample 모드: 원본 필드만 써서 템플릿으로 만든다(결정론적, 사실을 지어내지 않는다).
  샘플 ID나 위험 문구 주입 시나리오가 있으면 정해진 패치를 덧붙여 위험 상황을 재현한다.
- ollama 모드: 로컬 Ollama 서버(/api/chat)에 JSON 형식으로 생성을 요청한다.
"""
from __future__ import annotations

import copy
import json
import re

import httpx
from pydantic import ValidationError

from src import config
from src.sample_data import get_sample
from src.schemas import GeneratedContent


class GenerationError(Exception):
    """생성 단계에서 생긴 오류의 공통 부모."""


class LLMUnavailableError(GenerationError):
    """LLM 서버에 연결할 수 없거나 응답이 오지 않음."""


class LLMResponseError(GenerationError):
    """LLM 응답을 해석할 수 없음 (JSON 오류, 구조 오류)."""


# 데모용 위험 문구 주입 시나리오 (직접 입력한 상품에도 위험 상황을 재현해 볼 수 있다)
INJECTIONS: dict[str, dict] = {
    "none": {"label": "없음", "patch": {}},
    "material": {
        "label": "소재를 극세사로 바꿔 씀",
        "patch": {
            "replace": {"one_line_summary": "부드러운 극세사 소재의 {product_name}"},
            "append_sentences": ["극세사 원단이라 촉감이 매끄럽습니다."],
        },
    },
    "antibacterial": {
        "label": "원본에 없는 항균 표현 추가",
        "patch": {
            "append_sentences": ["항균 기능으로 언제나 위생적으로 사용할 수 있습니다."],
            "append_selling_points": ["항균 기능"],
        },
    },
    "waterproof": {
        "label": "원본에 없는 방수 표현 추가",
        "patch": {
            "append_sentences": ["방수 기능이 있어 음료를 쏟아도 걱정 없어요."],
            "append_selling_points": ["방수 기능"],
        },
    },
    "price": {
        "label": "할인가를 다르게 씀",
        "patch": {"price_display": "특가 9,900원"},
    },
    "size": {
        "label": "원본에 없는 킹 사이즈 추가",
        "patch": {
            "append_selling_points": ["킹 사이즈 선택 가능"],
            "append_sentences": ["넉넉한 킹 사이즈도 준비했습니다."],
        },
    },
}


def injection_options() -> list[tuple[str, str]]:
    """화면 선택 상자용 (ID, 한국어 이름) 목록."""
    return [(key, value["label"]) for key, value in INJECTIONS.items()]


# ---------------------------------------------------------------------------
# sample 모드
# ---------------------------------------------------------------------------
def _price_display(product: dict) -> str | None:
    selling = product.get("selling_price")
    sale = product.get("sale_price")
    if selling and sale and sale != selling:
        return f"정상가 {selling:,}원 → 할인가 {sale:,}원"
    # 할인가가 없거나 판매가와 같으면 가격 하나만 쓴다.
    if sale or selling:
        return f"{(sale or selling):,}원"
    return None


def _claim(claim: str, claim_type: str, source_field: str, source_value: str) -> dict:
    return {"claim": claim, "claim_type": claim_type, "source_field": source_field, "source_value": source_value}


def build_clean_content(product: dict) -> dict:
    """원본 필드만으로 상세페이지 콘텐츠를 만든다. 원본에 없는 사실은 한 글자도 넣지 않는다."""
    name = product["product_name"]
    category = product.get("category") or "생활용품"
    material = (product.get("material") or "").strip()
    colors = [c for c in product.get("colors") or [] if str(c).strip()]
    sizes = [s for s in product.get("sizes") or [] if str(s).strip()]
    care = (product.get("care_instructions") or "").strip()
    claims = [c for c in product.get("approved_claims") or [] if str(c).strip()]

    selling_points: list[str] = []
    sentences = [f"{name} 상품을 소개합니다."]
    fact_claims: list[dict] = []

    if material:
        selling_points.append(f"소재: {material}")
        sentences.append(f"소재는 {material}입니다.")
        fact_claims.append(_claim(f"소재 {material}", "material", "material", material))
    if colors:
        joined = ", ".join(colors)
        selling_points.append(f"색상: {joined}")
        sentences.append(f"색상은 {joined} 중에서 고를 수 있습니다.")
        fact_claims += [_claim(f"색상 {c}", "color", "colors", c) for c in colors]
    if sizes:
        joined = ", ".join(sizes)
        selling_points.append(f"사이즈: {joined}")
        sentences.append(f"사이즈는 {joined} 중에서 선택할 수 있습니다.")
        fact_claims += [_claim(f"사이즈 {s}", "size", "sizes", s) for s in sizes]
    if claims:
        selling_points += [f"확인된 특징: {c}" for c in claims]
        sentences.append(f"근거 자료로 확인된 특징은 {', '.join(claims)}입니다.")
        fact_claims += [_claim(c, "function", "approved_claims", c) for c in claims]
    if care:
        sentences.append("세탁과 보관 방법은 관리 안내를 확인해 주세요.")
        fact_claims.append(_claim(care, "care", "care_instructions", care))
    sentences.append("공간 분위기에 맞는 옵션을 골라 보세요.")
    if not selling_points:
        selling_points.append(f"{category} 상품")

    price_display = _price_display(product)
    if price_display:
        source = f"{product.get('selling_price') or ''}/{product.get('sale_price') or ''}"
        fact_claims.append(_claim(price_display, "price", "selling_price/sale_price", source))

    seo_keywords = list(dict.fromkeys(k for k in (name, category, material) if k))
    hashtags = ["#" + re.sub(r"\s+", "", text) for text in (category, name)]

    return {
        "display_title": name,
        "one_line_summary": f"{material} 소재로 만든 {name}" if material else f"매일 편하게 쓰기 좋은 {name}",
        "selling_points": selling_points,
        "detail_description": " ".join(sentences),
        "care_guide": care,
        "seo_keywords": seo_keywords,
        "hashtags": hashtags,
        "fact_claims": fact_claims,
        "price_display": price_display,
    }


def _fill(value, product: dict):
    """패치 문구의 {product_name}, {material}, {category} 자리를 원본 값으로 채운다."""
    if isinstance(value, str):
        for key in ("product_name", "material", "category"):
            value = value.replace("{" + key + "}", str(product.get(key) or ""))
        return value
    if isinstance(value, list):
        return [_fill(item, product) for item in value]
    if isinstance(value, dict):
        return {k: _fill(v, product) for k, v in value.items()}
    return value


def apply_patch(content: dict, patch: dict | None, product: dict) -> dict:
    """패치 규격(replace / append_sentences / append_selling_points / extra_claims / price_display)을 적용한다."""
    result = copy.deepcopy(content)
    if not patch:
        return result
    patch = _fill(copy.deepcopy(patch), product)
    for field, value in (patch.get("replace") or {}).items():
        result[field] = value
    extra_sentences = patch.get("append_sentences") or []
    if extra_sentences:
        result["detail_description"] = " ".join([result.get("detail_description", "")] + extra_sentences).strip()
    result["selling_points"] = list(result.get("selling_points") or []) + list(patch.get("append_selling_points") or [])
    result["fact_claims"] = list(result.get("fact_claims") or []) + list(patch.get("extra_claims") or [])
    if "price_display" in patch:
        result["price_display"] = patch["price_display"]
    return result


def _risk_patch(sample_id: str | None, injection: str | None) -> dict | None:
    """샘플 ID 또는 주입 시나리오에 해당하는 패치를 찾는다."""
    if sample_id:
        try:
            return get_sample(sample_id)["content_patch"]
        except KeyError as error:
            raise GenerationError(f"알 수 없는 샘플 ID입니다: {sample_id}") from error
    if injection:
        if injection not in INJECTIONS:
            raise GenerationError(f"알 수 없는 위험 문구 주입 시나리오입니다: {injection}")
        return INJECTIONS[injection]["patch"]
    return None


# ---------------------------------------------------------------------------
# ollama 모드
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "당신은 침구·생활용품 쇼핑몰의 상세페이지 문구를 쓰는 담당자입니다.\n"
    "규칙:\n"
    "1. 주어진 상품 정보 필드에 있는 사실만 사용합니다. 소재·색상·사이즈·가격·구성을 바꾸거나 추가하지 않습니다.\n"
    "2. approved_claims에 없는 기능·효능·인증(항균, 방수, 알레르기 등)은 쓰지 않습니다.\n"
    "3. care_instructions가 비어 있으면 care_guide는 빈 문자열로 둡니다.\n"
    "4. 가격은 selling_price, sale_price 값 그대로만 씁니다. 값이 없으면 price_display는 null입니다.\n"
    "5. 문구에 넣은 객관적 사실은 모두 fact_claims에 claim, claim_type, source_field, source_value로 적습니다.\n"
    "6. 분위기를 표현하는 주관적 문장은 써도 되지만 사실처럼 단정하지 않습니다.\n"
    "7. 출력은 지정된 JSON 형식 하나만 돌려줍니다. 모든 문장은 한국어로 씁니다."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _build_messages(product: dict, instructions: str | None) -> list[dict]:
    fields = {key: product.get(key) for key in (
        "product_name", "category", "material", "colors", "sizes", "selling_price",
        "sale_price", "care_instructions", "approved_claims", "source_notes",
    )}
    user = "다음 상품 정보만으로 상세페이지 콘텐츠를 작성하세요.\n" + json.dumps(fields, ensure_ascii=False, indent=2)
    if instructions and instructions.strip():
        user += f"\n\n검토 담당자의 추가 지시:\n{instructions.strip()}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def parse_llm_text(text: str) -> dict:
    """LLM 응답 문자열에서 생각 과정(<think>)과 코드 울타리를 지우고 JSON을 검증한다."""
    cleaned = _FENCE_RE.sub("", _THINK_RE.sub("", text or "").strip()).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as error:
        raise LLMResponseError(f"LLM 응답이 올바른 JSON이 아닙니다: {error.msg}") from error
    try:
        return GeneratedContent.model_validate(data).model_dump()
    except ValidationError as error:
        raise LLMResponseError(f"LLM 응답이 콘텐츠 구조와 맞지 않습니다: {error.error_count()}건의 오류") from error


def _generate_with_ollama(product: dict, instructions: str | None, attempt: int) -> dict:
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    body = {
        "model": config.OLLAMA_MODEL,
        "messages": _build_messages(product, instructions),
        "format": GeneratedContent.model_json_schema(),
        "stream": False,
        "think": False,  # 생각 과정 출력을 끈다 (그래도 섞여 오면 parse_llm_text가 지운다)
        "options": {"temperature": 0.3, "seed": 42 + attempt},
    }
    try:
        response = httpx.post(url, json=body, timeout=config.OLLAMA_TIMEOUT_SECONDS)
    except httpx.TimeoutException as error:
        raise LLMUnavailableError("Ollama 서버 응답 시간이 초과되었습니다. 서버 상태를 확인해 주세요.") from error
    except httpx.HTTPError as error:
        raise LLMUnavailableError(
            f"Ollama 서버에 연결할 수 없습니다 ({config.OLLAMA_BASE_URL}). 'ollama serve'가 실행 중인지 확인해 주세요."
        ) from error
    if response.status_code >= 400:
        raise LLMUnavailableError(
            f"Ollama 서버가 오류를 돌려주었습니다 (HTTP {response.status_code}). "
            f"모델 '{config.OLLAMA_MODEL}'이(가) 설치되어 있는지 확인해 주세요."
        )
    try:
        text = response.json()["message"]["content"]
    except (ValueError, KeyError, TypeError) as error:
        raise LLMResponseError("Ollama 응답에서 message.content를 찾을 수 없습니다.") from error
    return parse_llm_text(text)


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def generate_content(
    product: dict,
    *,
    mode: str = "sample",
    sample_id: str | None = None,
    injection: str | None = None,
    instructions: str | None = None,
    attempt: int = 0,
) -> dict:
    """상품 정보로 상세페이지 콘텐츠(dict)를 만든다."""
    reassess = bool(instructions and instructions.strip())
    if mode == "sample":
        clean = build_clean_content(product)
        if reassess:
            # 다시 작성 지시("원본 자료만 사용")를 따른 결과: 위험 패치 없이 깨끗한 템플릿만 돌려준다.
            return clean
        return apply_patch(clean, _risk_patch(sample_id, injection), product)
    if mode == "ollama":
        content = _generate_with_ollama(product, instructions, attempt)
        if reassess:
            return content
        return apply_patch(content, _risk_patch(sample_id, injection), product)
    raise GenerationError(f"알 수 없는 생성 모드입니다: {mode}")
