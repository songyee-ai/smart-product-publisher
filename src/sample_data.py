"""평가·시연용 고정 샘플 20건 (가상 브랜드 "굿홈앤리빙"의 침구·생활용품).

- 기본(S01~S10): 자주 생기는 위험 유형을 하나씩 담은 기본 시나리오
- 함정(S11~S20): 규칙이 놓치거나 괜히 멈추기 쉬운 경계 사례

expected_review(사람 승인 필요 여부)는 규칙의 판정 결과가 아니라
꼼꼼한 검토 담당자라면 어떻게 판단할지를 기준으로 붙였다.
그래서 일부 함정 샘플은 최종 규칙 조합에서도 놓치거나(미탐) 괜히 멈춘다(오탐).
"""
from __future__ import annotations

import copy

BRAND = "굿홈앤리빙"

_BASE_PRODUCT = {
    "category": "침구",
    "material": "면 100%",
    "colors": ["아이보리", "그레이"],
    "sizes": ["슈퍼싱글", "퀸"],
    "selling_price": 79000,
    "sale_price": 59000,
    "care_instructions": "30도 이하 미온수에 중성세제로 단독 세탁하고 그늘에서 말려 주세요.",
    "approved_claims": [],
    "source_notes": "구성: 이불 1장.",
}


def _product(product_id: str, product_name: str, **overrides) -> dict:
    """기본 상품 정보에 샘플별로 바뀌는 값만 덮어쓴다."""
    product = copy.deepcopy(_BASE_PRODUCT)
    product.update({"product_id": product_id, "product_name": f"{BRAND} {product_name}"})
    product.update(overrides)
    return product


SAMPLES: list[dict] = [
    # ---------------------------------------------------------------- 기본
    {
        "sample_id": "S01",
        "title": "정상 상품 (원본 정보만 사용)",
        "product": _product("GH-001", "데일리 순면 차렵이불"),
        "content_patch": None,
        "expected_review": False,
        "expected_reason": "원본 정보만 사용했고 위험 표현이 없어 바로 게시해도 된다.",
        "group": "기본",
    },
    {
        "sample_id": "S02",
        "title": "소재 불일치 (순면 상품을 극세사로 표현)",
        "product": _product("GH-002", "순면 차렵이불", material="순면 100%"),
        "content_patch": {
            "replace": {"one_line_summary": "포근한 극세사 차렵이불"},
            "append_sentences": ["극세사 원단이라 손에 닿는 느낌이 매끄러워요."],
        },
        "expected_review": True,
        "expected_reason": "원본 소재는 순면인데 본문에 극세사라고 썼다(fact_claims에는 빠져 있음).",
        "group": "기본",
    },
    {
        "sample_id": "S03",
        "title": "근거 없는 항균 표현",
        "product": _product("GH-003", "베이직 베개커버", category="침구"),
        "content_patch": {
            "append_sentences": ["항균 기능으로 세균 번식을 막아 줍니다."],
            "append_selling_points": ["항균 기능"],
        },
        "expected_review": True,
        "expected_reason": "항균 기능을 입증한 자료가 없다.",
        "group": "기본",
    },
    {
        "sample_id": "S04",
        "title": "근거 없는 알레르기 차단 표현",
        "product": _product("GH-004", "사계절 매트리스 커버"),
        "content_patch": {
            "append_sentences": ["알레르기 차단 효과가 있어 민감한 분도 편하게 쓸 수 있어요."],
        },
        "expected_review": True,
        "expected_reason": "알레르기 차단은 효능 주장인데 근거 자료가 없다.",
        "group": "기본",
    },
    {
        "sample_id": "S05",
        "title": "원본에 없는 킹 사이즈 추가",
        "product": _product("GH-005", "워싱 면 이불커버"),
        "content_patch": {
            "append_selling_points": ["킹 사이즈까지 선택 가능"],
            "append_sentences": ["넉넉한 킹 사이즈도 준비했습니다."],
        },
        "expected_review": True,
        "expected_reason": "원본 사이즈는 슈퍼싱글·퀸뿐인데 킹 사이즈를 안내했다.",
        "group": "기본",
    },
    {
        "sample_id": "S06",
        "title": "할인가 불일치",
        "product": _product("GH-006", "호텔식 면 침대 패드", selling_price=89000, sale_price=69000),
        "content_patch": {"price_display": "할인가 59,000원"},
        "expected_review": True,
        "expected_reason": "원본 할인가는 69,000원인데 59,000원으로 표시했다.",
        "group": "기본",
    },
    {
        "sample_id": "S07",
        "title": "관리 방법 누락",
        "product": _product("GH-007", "면 누빔 패드", care_instructions=""),
        "content_patch": None,
        "expected_review": True,
        "expected_reason": "필수 정보인 관리 방법이 원본에 비어 있어 담당자 확인이 필요하다.",
        "group": "기본",
    },
    {
        "sample_id": "S08",
        "title": "승인된 기능 표현만 사용",
        "product": _product("GH-008", "항균 가공 면 베개커버",
                            approved_claims=["항균 가공 원단 사용(시험성적서 보유)"]),
        "content_patch": None,
        "expected_review": False,
        "expected_reason": "항균 표현이 있지만 시험성적서로 승인된 기능 범위 안이다.",
        "group": "기본",
    },
    {
        "sample_id": "S09",
        "title": "근거 없는 방수·발수 표현",
        "product": _product("GH-009", "면 매트리스 커버"),
        "content_patch": {
            "append_sentences": ["방수·발수 원단이라 아이 방에도 안심하고 쓸 수 있어요."],
        },
        "expected_review": True,
        "expected_reason": "방수·발수 기능을 입증한 자료가 없다.",
        "group": "기본",
    },
    {
        "sample_id": "S10",
        "title": "주관적 분위기 표현만 사용",
        "product": _product("GH-010", "포근 면 블랭킷", category="생활용품"),
        "content_patch": {
            "append_sentences": ["포근하고 아늑한 분위기로 침실을 꾸며 보세요."],
        },
        "expected_review": False,
        "expected_reason": "사실 주장이 아닌 분위기 표현이라 그대로 게시해도 된다.",
        "group": "기본",
    },
    # ---------------------------------------------------------------- 함정
    {
        "sample_id": "S11",
        "title": "키워드 없는 항균 효능 바꿔 말하기",
        "product": _product("GH-011", "면 거즈 이불"),
        "content_patch": {
            "append_sentences": ["세균 걱정 없는 위생적인 이불로 매일 산뜻하게 사용하세요."],
        },
        "expected_review": True,
        "expected_reason": "'항균'이라는 말은 없지만 위생 효능을 주장한다. 근거가 없으니 멈춰야 한다.",
        "group": "함정",
    },
    {
        "sample_id": "S12",
        "title": "키워드 없는 방수 기능 바꿔 말하기",
        "product": _product("GH-012", "면 방석 커버", category="생활용품"),
        "content_patch": {
            "append_sentences": ["물이 스며들지 않는 원단이라 음료를 쏟아도 안심이에요."],
        },
        "expected_review": True,
        "expected_reason": "'방수'라는 말은 없지만 방수 기능을 주장한다. 근거가 없으니 멈춰야 한다.",
        "group": "함정",
    },
    {
        "sample_id": "S13",
        "title": "기능을 부정하는 안내 문장",
        "product": _product("GH-013", "면 소파 패드", category="생활용품"),
        "content_patch": {
            "append_sentences": ["방수 기능은 없으니 음료를 쏟았을 때는 바로 닦아 주세요."],
        },
        "expected_review": False,
        "expected_reason": "방수 기능이 '없다'고 정확히 안내한 문장이라 문제가 없다.",
        "group": "함정",
    },
    {
        "sample_id": "S14",
        "title": "같은 뜻의 소재 표기 (면 100% = 순면)",
        "product": _product("GH-014", "데일리 베개커버"),
        "content_patch": {
            "replace": {"one_line_summary": "순면으로 만든 {product_name}"},
            "append_selling_points": ["순면(코튼 100%) 원단"],
            "append_sentences": ["순면 원단 특유의 부드러운 촉감을 느껴 보세요."],
        },
        "expected_review": False,
        "expected_reason": "원본 '면 100%'와 '순면', '코튼 100%'는 같은 뜻이다.",
        "group": "함정",
    },
    {
        "sample_id": "S15",
        "title": "원본에 없는 색상 이름 (크림색)",
        "product": _product("GH-015", "면 홑이불", colors=["아이보리", "베이지"]),
        "content_patch": {
            "append_sentences": ["은은한 크림색이 침실을 한층 밝혀 줍니다."],
        },
        "expected_review": True,
        "expected_reason": "원본 색상은 아이보리·베이지뿐이다. 크림색 옵션이 있는 것처럼 오해할 수 있다.",
        "group": "함정",
    },
    {
        "sample_id": "S16",
        "title": "어림한 가격 표현 (6만 원대)",
        "product": _product("GH-016", "면 차렵 이불세트"),
        "content_patch": {
            "append_sentences": ["6만 원대의 합리적인 가격으로 만나 보세요."],
        },
        "expected_review": True,
        "expected_reason": "실제 가격은 79,000원(할인가 59,000원)이라 '6만 원대'는 틀린 안내다.",
        "group": "함정",
    },
    {
        "sample_id": "S17",
        "title": "정확한 할인율 표기 (25% 할인)",
        "product": _product("GH-017", "면 여름 이불"),
        "content_patch": {
            "append_sentences": ["정상가 대비 25% 할인된 가격으로 만나 보세요."],
        },
        "expected_review": False,
        "expected_reason": "79,000원에서 59,000원은 약 25% 할인이라 맞는 표기다.",
        "group": "함정",
    },
    {
        "sample_id": "S18",
        "title": "원본에 없는 구성품 (베개커버 2장 포함)",
        "product": _product("GH-018", "면 이불", source_notes="구성: 이불 1장. 베개커버는 별도 판매."),
        "content_patch": {
            "append_sentences": ["베개커버 2장 포함 구성이라 바로 사용할 수 있어요."],
        },
        "expected_review": True,
        "expected_reason": "원본 메모에 베개커버는 별도 판매라고 적혀 있다.",
        "group": "함정",
    },
    {
        "sample_id": "S19",
        "title": "주관적 비유 표현 (호텔 같은)",
        "product": _product("GH-019", "면 침대 스커트",
                            care_instructions="베이킹소다를 푼 미온수에 손세탁하고 그늘에서 말려 주세요."),
        "content_patch": {
            "append_sentences": ["호텔 같은 침실 분위기를 집에서도 느껴 보세요."],
        },
        "expected_review": False,
        "expected_reason": "분위기를 빗댄 표현일 뿐 사실 주장이 아니다.",
        "group": "함정",
    },
    {
        "sample_id": "S20",
        "title": "알레르기 주의 안내 문장",
        "product": _product("GH-020", "면 쿠션 커버", category="생활용품"),
        "content_patch": {
            "append_sentences": ["알레르기가 있으신 분은 구매 전에 소재 정보를 꼭 확인해 주세요."],
        },
        "expected_review": False,
        "expected_reason": "효능 주장이 아니라 구매 전 확인을 권하는 주의 문장이다.",
        "group": "함정",
    },
]


def list_samples() -> list[dict]:
    """샘플 전체 목록 (원본이 바뀌지 않도록 복사본을 돌려준다)."""
    return copy.deepcopy(SAMPLES)


def get_sample(sample_id: str) -> dict:
    """샘플 ID로 샘플 하나를 찾는다. 없으면 KeyError."""
    for sample in SAMPLES:
        if sample["sample_id"] == sample_id:
            return copy.deepcopy(sample)
    raise KeyError(f"샘플을 찾을 수 없습니다: {sample_id}")
