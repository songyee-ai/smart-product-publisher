"""생성 콘텐츠 검증: 사람이 승인해야 하는지 판단하는 규칙 모음.

- A: 핵심 상품 정보 불일치 (소재·색상·사이즈·구성)
- B: 근거 없는 기능·효능·인증 표현
- C: 필수 상품 정보 누락
- D: 가격 정보 불일치
- E: 근거 없는 성능·효과 단정
- S: 출력 구조 오류 (항상 검사)

AI가 스스로 적은 fact_claims만 믿지 않고, 실제로 생성된 문장 전체를 훑어본다.
(본문에는 "극세사"라고 써 놓고 fact_claims에서는 빠뜨릴 수 있기 때문이다.)
"""
from __future__ import annotations

import re
from typing import Iterable

from pydantic import ValidationError

from src import config
from src.schemas import GeneratedContent

# 문장 검사 대상 필드 (순서대로 훑는다)
TEXT_FIELDS = ("display_title", "one_line_summary", "detail_description", "care_guide")
LIST_FIELDS = ("selling_points", "seo_keywords", "hashtags")

# 화면 메시지에 쓸 콘텐츠 필드의 한국어 이름
CONTENT_FIELD_LABELS = {
    "display_title": "상품 제목",
    "one_line_summary": "한 줄 요약",
    "detail_description": "상세 설명",
    "care_guide": "관리 안내",
    "selling_points": "핵심 장점",
    "seo_keywords": "검색 키워드",
    "hashtags": "해시태그",
    "fact_claims": "사실 주장 목록",
    "price_display": "가격 표시",
}


def field_label(field: str) -> str:
    """콘텐츠 필드 이름을 한국어로 바꾼다. 모르는 이름은 그대로 둔다."""
    return CONTENT_FIELD_LABELS.get(field, field)

# ---------------------------------------------------------------------------
# 사전: (대표 이름, 생성 문장에서 찾을 정규식들, 원본 값에서 같은 뜻으로 볼 표기들)
# 더 구체적인 표기를 앞에 둔다. 앞에서 찾은 위치와 겹치는 결과는 버린다.
# ---------------------------------------------------------------------------
MATERIALS: list[tuple[str, list[str], list[str]]] = [
    (
        "순면",
        [r"순면", r"면\s*100\s*%", r"코튼\s*100\s*%", r"100\s*%\s*(?:면|코튼)",
         r"cotton\s*100\s*%", r"100\s*%\s*cotton", r"퓨어\s*코튼"],
        ["순면", "면100%", "코튼100%", "100%면", "100%코튼", "cotton100%", "100%cotton", "퓨어코튼"],
    ),
    ("극세사", [r"극세사", r"마이크로\s*(?:화이바|파이버|화이버)", r"microfiber"],
     ["극세사", "마이크로화이바", "마이크로파이버", "마이크로화이버", "microfiber"]),
    ("텐셀", [r"텐셀", r"tencel", r"라이오셀", r"lyocell"], ["텐셀", "tencel", "라이오셀", "lyocell"]),
    ("모달", [r"모달", r"modal"], ["모달", "modal"]),
    ("린넨", [r"린넨", r"리넨", r"linen"], ["린넨", "리넨", "linen"]),
    ("실크", [r"실크", r"silk"], ["실크", "silk"]),
    ("울", [r"양모", r"wool", r"메리노\s*울", r"(?<![가-힣])울\s*(?:\d+\s*%|소재|원단|혼방)"],
     ["울", "양모", "wool"]),
    ("구스다운", [r"구스\s*다운", r"거위\s*털", r"goose\s*down"], ["구스다운", "거위털", "goosedown"]),
    ("덕다운", [r"덕\s*다운", r"오리\s*털", r"duck\s*down"], ["덕다운", "오리털", "duckdown"]),
    ("레이온", [r"레이온", r"rayon", r"인견", r"비스코스", r"viscose"],
     ["레이온", "rayon", "인견", "비스코스", "viscose"]),
    ("폴리에스터", [r"폴리에스터", r"폴리에스테르", r"polyester"],
     ["폴리에스터", "폴리에스테르", "polyester", "폴리"]),
    ("나일론", [r"나일론", r"nylon"], ["나일론", "nylon"]),
    ("아크릴", [r"아크릴", r"acrylic"], ["아크릴", "acrylic"]),
    ("스판덱스", [r"스판덱스", r"spandex", r"폴리우레탄"], ["스판덱스", "spandex", "폴리우레탄", "스판"]),
    ("대나무 섬유", [r"대나무\s*섬유", r"뱀부", r"bamboo"], ["대나무섬유", "뱀부", "bamboo"]),
    ("라텍스", [r"라텍스", r"latex"], ["라텍스", "latex"]),
    ("메모리폼", [r"메모리\s*폼"], ["메모리폼"]),
    # "면" 한 글자는 "표면", "하면서" 같은 말에도 들어 있어서 소재로 쓰인 경우만 찾는다.
    ("면", [r"코튼", r"cotton", r"(?<![가-힣])면\s*(?:\d+\s*%|소재|원단|혼방)"], ["면", "코튼", "cotton"]),
]

COLORS: list[tuple[str, list[str], list[str]]] = [
    ("차콜", [r"차콜", r"charcoal"], []),
    ("아이보리", [r"아이보리", r"ivory"], []),
    ("베이지", [r"베이지", r"beige"], []),
    ("화이트", [r"화이트", r"흰색", r"백색", r"white"], []),
    ("그레이", [r"그레이", r"회색", r"gray", r"grey"], []),
    ("네이비", [r"네이비", r"남색", r"navy"], []),
    ("블랙", [r"블랙", r"검정", r"검은색", r"black"], []),
    ("핑크", [r"핑크", r"분홍", r"pink"], []),
    ("블루", [r"블루", r"파란색", r"파랑", r"blue"], []),
    ("그린", [r"그린", r"초록", r"녹색", r"green"], []),
    ("민트", [r"민트", r"mint"], []),
    ("옐로우", [r"옐로우", r"옐로", r"노란색", r"노랑", r"yellow"], []),
    ("브라운", [r"브라운", r"갈색", r"brown"], []),
    ("크림", [r"크림"], []),
    ("라벤더", [r"라벤더"], []),
    ("퍼플", [r"퍼플", r"보라색", r"보랏빛", r"purple"], []),
    ("카키", [r"카키", r"khaki"], []),
    ("오트밀", [r"오트밀"], []),
    ("버건디", [r"버건디", r"burgundy"], []),
    ("코랄", [r"코랄", r"coral"], []),
    ("머스타드", [r"머스타드"], []),
]

# 사이즈는 앞 글자가 한글이면 다른 낱말("베이킹", "마킹")로 보고 건너뛴다.
_B = r"(?<![가-힣])"
SIZES: list[tuple[str, list[str], list[str]]] = [
    ("라지킹", [_B + r"라지\s*킹"], []),
    ("패밀리킹", [_B + r"패밀리\s*킹"], []),
    ("슈퍼싱글", [_B + r"슈퍼\s*싱글"], []),
    ("미니싱글", [_B + r"미니\s*싱글"], []),
    ("싱글", [_B + r"싱글"], []),
    ("더블", [_B + r"더블(?!\s*(?:거즈|가제))"], []),
    ("퀸", [_B + r"퀸"], []),
    ("킹", [_B + r"킹"], []),
]

# 원본 사이즈 칸에 영문 약자만 적힌 경우의 뜻
SIZE_LETTERS = {
    "S": "싱글", "SS": "슈퍼싱글", "MS": "미니싱글", "D": "더블",
    "Q": "퀸", "K": "킹", "LK": "라지킹", "FK": "패밀리킹",
}

# 구성 표현: "베개커버 2장 포함", "4종 구성" 등
COMPOSITION_RE = re.compile(
    r"(\d+)\s*(종|장|개|매|피스|p|입|세트)\s*(?:구성|세트|포함|증정|패키지|set)", re.IGNORECASE
)
COMPOSITION_CORE_RE = re.compile(r"(\d+)\s*(종|장|개|매|피스|p|입|세트)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# 기준 B: 기능·효능·인증 표현 묶음
# negatable=False 인 묶음은 부정형 자체가 주장이다 (예: "유해물질이 검출되지 않았습니다").
# ---------------------------------------------------------------------------
CLAIM_FAMILIES: list[dict] = [
    {"name": "항균", "patterns": [r"항균", r"살균", r"멸균", r"제균"], "negatable": True},
    {"name": "진드기 차단", "patterns": [r"진드기"], "negatable": True},
    {"name": "알레르기 완화", "patterns": [r"알레르기", r"알러지", r"비염"], "negatable": True},
    {"name": "아토피", "patterns": [r"아토피"], "negatable": True},
    {"name": "방수", "patterns": [r"방수", r"워터\s*프루프", r"waterproof"], "negatable": True},
    {"name": "발수", "patterns": [r"발수"], "negatable": True},
    {"name": "오염 방지", "patterns": [r"오염\s*방지", r"방오"], "negatable": True},
    {"name": "탈취", "patterns": [r"탈취", r"소취", r"냄새\s*제거"], "negatable": True},
    {"name": "정전기 방지", "patterns": [r"정전기\s*방지"], "negatable": True},
    {"name": "친환경 인증", "patterns": [r"친환경"], "negatable": True},
    {"name": "KC 인증", "patterns": [r"kc\s*인증", r"kc\s*마크"], "negatable": True},
    {"name": "OEKO-TEX 인증", "patterns": [r"oeko[\s-]*tex", r"오코\s*텍스"], "negatable": True},
    {"name": "특허", "patterns": [r"특허"], "negatable": True},
    {"name": "수면 효능", "patterns": [r"숙면", r"수면\s*(?:의\s*)?질"], "negatable": True},
    {"name": "의학적 효능", "patterns": [r"혈액\s*순환", r"치료", r"통증\s*완화"], "negatable": True},
    # 로컬 LLM 시험 생성에서 실제로 새어 나온 건강·성능 단정 표현을 보고 추가한 묶음
    {"name": "건강·성능 효능", "patterns": [r"호흡기", r"건강에\s*좋", r"체온\s*조절", r"방독"],
     "negatable": True},
    {"name": "유해물질 불검출", "patterns": [r"유해\s*물질", r"불검출", r"무독성", r"포름\s*알데히드"],
     "negatable": False},
    # "피부 자극"뿐 아니라 "피부에 자극", "피부의 자극"처럼 조사가 끼어도 잡는다.
    {"name": "피부 자극 없음", "patterns": [r"피부(?:에|의|가)?\s*자극", r"저자극", r"무자극", r"민감성\s*피부"],
     "negatable": False},
    {"name": "무형광", "patterns": [r"무형광", r"형광\s*증백제"], "negatable": False},
]

# 부정 표현: 키워드 뒤 같은 문장 안(가까운 거리)에 나오면 그 기능을 부정한 것으로 본다.
NEGATION_RE = re.compile(
    r"(없습니다|없어요|없음|없으니|없으며|없고|없지만|없다|없었|않습니다|않았습니다|않아요|않음|않으며|"
    r"않았으며|않았음|않았고|않았다|않는다|않은|않고|않으니|않지만|아닙니다|아니에요|아님|아니며|"
    r"불가|미적용|미가공|미처리|"
    r"안\s*(?:되|돼|됩))"
)
# "걱정 없는", "고민 없이"처럼 '없다'가 효능을 강조하는 말이면 부정으로 보지 않는다.
WORRY_RE = re.compile(r"(걱정|고민|염려|부담|근심)\S{0,2}\s*$")
NEGATION_WINDOW = 20
# 부정어 바로 앞에 이런 동사가 오면 '기능이 사라지지 않는다'는 지속성 주장이다 (부정 아님).
PERSISTENCE_VERBS = r"(?:줄지|줄어들지|벗겨지지|사라지지|떨어지지|약해지지|빠지지|없어지지|변하지|손상되지)"
PERSISTENCE_RE = re.compile(PERSISTENCE_VERBS + r"\s*$")

# ---------------------------------------------------------------------------
# 기준 D: 가격 표현
# ---------------------------------------------------------------------------
KOREAN_PRICE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*만\s*(?:(\d+)\s*천\s*)?원(\s*대)?")
NUMBER_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원(?![단형룸목하래료칙인산])(\s*대)?")
PERCENT_RES = [
    re.compile(r"(\d+(?:\.\d+)?)\s*%\s*(?:할인|세일|off)", re.IGNORECASE),
    re.compile(r"(?:할인율|할인|세일)\s*(\d+(?:\.\d+)?)\s*%", re.IGNORECASE),
]
DISCOUNT_WORDS = ("할인", "절약", "저렴")


def explain_rules() -> dict[str, str]:
    """기준 문자별 한 줄 설명 (화면·보고서에서 사용)."""
    return {
        "A": "원본에 없는 소재·색상·사이즈·구성이 생성 문구에 나오면 멈춘다 (같은 뜻의 표기는 같은 것으로 본다).",
        "B": "근거 자료(승인된 기능)에 없는 기능·효능·인증 표현이 나오면 멈춘다 (같은 문장에서 부정한 경우는 제외).",
        "C": "필수 상품 정보가 원본에 비어 있거나, 원본에 없는 관리 방법을 임의로 쓰면 멈춘다.",
        "D": "생성 문구의 가격·할인율이 원본 판매가·할인가와 맞지 않으면 멈춘다.",
        "E": "근거 자료에 없는 성능·효과 단정(내구성, 세탁 후 유지, 성능, 효과, 보장 등)이 나오면 멈춘다.",
        "S": "생성 결과가 정해진 구조(필수 항목·자료형)를 지키지 않으면 멈춘다. 이 기준은 항상 검사한다.",
    }


# ---------------------------------------------------------------------------
# 공통 도우미
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    """비교용 정규화: 소문자로 바꾸고 공백·기호를 지운다(%는 남긴다)."""
    return re.sub(r"[^0-9a-z가-힣%]", "", str(text or "").lower())


def _flag(rule, code, message, field="", source_value="", generated_value="", evidence="") -> dict:
    return {
        "rule": rule,
        "code": code,
        "message": message,
        "field": field,
        "source_value": str(source_value),
        "generated_value": str(generated_value),
        "evidence": str(evidence)[:200],
    }


def _split_sentences(text: str) -> list[str]:
    """마침표·물음표·느낌표·줄바꿈 기준으로 문장을 나눈다."""
    parts = re.split(r"(?<=[.!?。])\s+|\n+", str(text or ""))
    return [part.strip() for part in parts if part.strip()]


def _collect_texts(content: dict) -> list[tuple[str, str]]:
    """검사할 (필드 이름, 문장) 목록. 목록형 필드는 항목마다, 긴 글은 문장마다 나눈다."""
    items: list[tuple[str, str]] = []
    for field in TEXT_FIELDS:
        for sentence in _split_sentences(content.get(field) or ""):
            items.append((field, sentence))
    for field in LIST_FIELDS:
        for value in content.get(field) or []:
            if str(value).strip():
                items.append((field, str(value)))
    return items


def _claim_texts(content: dict, claim_type: str | None = None) -> list[tuple[str, str]]:
    """fact_claims의 claim 문장 목록 (claim_type을 주면 그 종류만)."""
    items = []
    for claim in content.get("fact_claims") or []:
        if claim_type is None or claim.get("claim_type") == claim_type:
            items.append(("fact_claims", str(claim.get("claim", ""))))
    return items


def _detect(text: str, entries) -> dict[str, str]:
    """사전 단어를 찾아 {대표 이름: 실제로 쓰인 표기}를 돌려준다. 겹치는 위치는 앞 항목이 우선."""
    found: dict[str, str] = {}
    taken: list[tuple[int, int]] = []
    for canonical, patterns, _aliases in entries:
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                start, end = match.span()
                if any(start < t_end and t_start < end for t_start, t_end in taken):
                    continue
                taken.append((start, end))
                found.setdefault(canonical, match.group(0))
    return found


def _present_in_source(canonical: str, entries, source_text: str) -> bool:
    """원본 값에 같은 뜻의 표기가 있는지 확인한다."""
    if canonical in _detect(source_text, entries):
        return True
    normalized = _norm(source_text)
    for name, _patterns, aliases in entries:
        if name == canonical:
            return any(_norm(alias) in normalized for alias in aliases if alias)
    return False


def _size_source_text(product: dict) -> str:
    """사이즈 원본 문자열. "Q", "SS" 같은 약자는 한글 이름으로 풀어 쓴다."""
    parts = []
    for size in product.get("sizes") or []:
        value = str(size).strip()
        parts.append(SIZE_LETTERS.get(value.upper(), value))
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# 기준 S: 출력 구조
# ---------------------------------------------------------------------------
def _check_structure(content) -> list[dict]:
    if content is None:
        return [_flag("S", "missing_content", "생성 결과가 없습니다.", field="content")]
    if not isinstance(content, dict):
        return [_flag("S", "invalid_type", "생성 결과가 올바른 형태(딕셔너리)가 아닙니다.",
                      field="content", generated_value=type(content).__name__)]
    try:
        GeneratedContent.model_validate(content)
    except ValidationError as error:
        problems = ", ".join(".".join(str(p) for p in err["loc"]) for err in error.errors())
        return [_flag("S", "schema_error", f"생성 결과의 구조가 올바르지 않습니다: {problems}",
                      field=problems, evidence=str(error.errors()[0].get("msg", "")))]
    return []


# ---------------------------------------------------------------------------
# 기준 A: 핵심 상품 정보 불일치
# ---------------------------------------------------------------------------
def _check_core_info(product: dict, content: dict) -> list[dict]:
    texts = _collect_texts(content) + _claim_texts(content)
    name = product.get("product_name", "")
    targets = [
        ("material", "소재", MATERIALS, f"{product.get('material', '')} {name}", product.get("material", "")),
        ("colors", "색상", COLORS, f"{', '.join(product.get('colors') or [])} {name}",
         ", ".join(product.get("colors") or [])),
        ("sizes", "사이즈", SIZES, f"{_size_source_text(product)} {name}", ", ".join(product.get("sizes") or [])),
    ]
    code_names = {"material": "material_mismatch", "colors": "color_mismatch", "sizes": "size_mismatch"}
    flags: list[dict] = []
    for field, label, entries, source_text, source_value in targets:
        # 같은 단어라도 위치(필드)가 다르면 따로 보고한다. 담당자가 고칠 곳을 모두 볼 수 있게 하기 위해서다.
        reported: set[tuple[str, str]] = set()
        for text_field, sentence in texts:
            for canonical, written in _detect(sentence, entries).items():
                key = (canonical, text_field)
                if key in reported or _present_in_source(canonical, entries, source_text):
                    continue
                reported.add(key)
                flags.append(_flag(
                    "A", code_names[field],
                    f"원본 {label}에 없는 '{written}' 표현이 {field_label(text_field)}에 있습니다.",
                    field=field, source_value=source_value, generated_value=written, evidence=sentence,
                ))
    flags.extend(_check_composition(product, content, texts))
    return flags


def _check_composition(product: dict, content: dict, texts) -> list[dict]:
    """구성 표현("베개커버 2장 포함")이 원본 메모·상품명에 있는지 확인한다."""
    source = _norm(f"{product.get('source_notes', '')} {product.get('product_name', '')}")
    flags: list[dict] = []
    reported: set[str] = set()

    def add(core: str, sentence: str) -> None:
        if core in reported:
            return
        reported.add(core)
        flags.append(_flag(
            "A", "composition_unverified",
            f"원본 자료에서 확인되지 않는 구성 표현('{core}')이 있습니다.",
            field="source_notes", source_value=product.get("source_notes", ""),
            generated_value=core, evidence=sentence,
        ))

    for _field, sentence in texts:
        for match in COMPOSITION_RE.finditer(sentence):
            core = _norm(match.group(1) + match.group(2))
            if core not in source:
                add(core, sentence)

    # AI가 스스로 구성 주장이라고 적은 항목도 확인한다.
    for claim in content.get("fact_claims") or []:
        if claim.get("claim_type") != "composition":
            continue
        text = str(claim.get("claim", ""))
        # 개수("2장", "3종")가 있는 주장만 구성 주장으로 본다.
        # LLM은 "면 100%로 구성됩니다" 같은 소재 문장도 composition으로 분류하는데,
        # 이런 문장의 소재·색상·사이즈 오류는 위의 사전 검사가 따로 잡는다.
        for match in COMPOSITION_CORE_RE.finditer(text):
            core = _norm(match.group(1) + match.group(2))
            if core not in source:
                add(core, text)
    return flags


# ---------------------------------------------------------------------------
# 기준 B: 근거 없는 기능·효능·인증 표현
# ---------------------------------------------------------------------------
def _is_negated(sentence: str, end: int) -> bool:
    """키워드 바로 뒤(같은 문장 안)에 부정 표현이 있으면 True."""
    window = sentence[end:end + NEGATION_WINDOW]
    for match in NEGATION_RE.finditer(window):
        before = sentence[:end + match.start()]
        if WORRY_RE.search(before):
            continue
        # "줄지 않습니다", "벗겨지지 않아요"는 기능이 오래간다는 '긍정' 주장이라 부정으로 보지 않는다.
        if PERSISTENCE_RE.search(window[:match.start()]):
            continue
        return True
    return False


def _plain_keyword(pattern: str) -> str:
    """정규식에서 공백 허용 표시(\\s*, [\\s-]*)를 지워 비교용 낱말로 만든다."""
    return _norm(pattern.replace("[\\s-]*", "").replace("\\s*", ""))


def _family_supported(family: dict, written: str, sentence: str, product: dict) -> bool:
    """승인된 기능 목록이나 원본 메모에 근거가 있으면 True."""
    # 승인된 기능 문구에 '이 묶음의 키워드'가 들어 있을 때만 근거로 인정한다.
    # (승인된 기능이 같은 문장에 있다는 이유만으로 다른 기능까지 통과시키지 않는다.
    #  예: 승인 기능이 '항균'뿐인데 "항균과 방수 기능"이라고 쓰면 방수는 걸려야 한다.)
    keys = [_norm(written)] + [_plain_keyword(p) for p in family["patterns"]]
    for claim in product.get("approved_claims") or []:
        norm_claim = _norm(claim)
        if norm_claim and any(key and key in norm_claim for key in keys):
            return True
    # 원본 메모는 그 기능을 '부정하지 않은' 문장에 있을 때만 근거로 인정한다.
    for note in _split_sentences(product.get("source_notes", "")):
        for pattern in family["patterns"]:
            for match in re.finditer(pattern, note, re.IGNORECASE):
                if not _is_negated(note, match.end()):
                    return True
    return False


def _check_claims(product: dict, content: dict, negation_guard: bool) -> list[dict]:
    texts = _collect_texts(content) + _claim_texts(content, "function")
    flags: list[dict] = []
    # (표현 묶음, 필드)마다 한 번씩 보고한다. 같은 묶음이 여러 필드에 있으면 모두 보여 준다.
    reported: set[tuple[str, str]] = set()
    flagged_sentences: set[str] = set()
    for family in CLAIM_FAMILIES:
        for text_field, sentence in texts:
            if (family["name"], text_field) in reported:
                continue
            for pattern in family["patterns"]:
                match = next(
                    (m for m in re.finditer(pattern, sentence, re.IGNORECASE)
                     if not (negation_guard and family["negatable"] and _is_negated(sentence, m.end()))),
                    None,
                )
                if match is None or _family_supported(family, match.group(0), sentence, product):
                    continue
                reported.add((family["name"], text_field))
                flagged_sentences.add(sentence)
                flags.append(_flag(
                    "B", "unsupported_claim",
                    f"근거 자료에 없는 '{family['name']}' 관련 표현이 {field_label(text_field)}에 있습니다.",
                    field=text_field, source_value=", ".join(product.get("approved_claims") or []),
                    generated_value=match.group(0), evidence=sentence,
                ))
                break

    # AI가 기능 주장이라고 스스로 적었는데 승인 목록에 없는 경우 (키워드가 없어도 잡는다)
    approved = [_norm(c) for c in product.get("approved_claims") or [] if _norm(c)]
    for claim in content.get("fact_claims") or []:
        if claim.get("claim_type") != "function":
            continue
        text = str(claim.get("claim", ""))
        norm_text = _norm(text)
        if not norm_text or text in flagged_sentences:
            continue
        if any(norm_text in a or a in norm_text for a in approved):
            continue
        flags.append(_flag(
            "B", "unsupported_function_claim",
            "승인된 기능 목록에 없는 기능 주장이 사실 주장 목록에 있습니다.",
            field="fact_claims", source_value=", ".join(product.get("approved_claims") or []),
            generated_value=text, evidence=text,
        ))
    return flags


# ---------------------------------------------------------------------------
# 기준 E: 근거 없는 성능·효과 단정
# B는 '항균·방수'처럼 이름이 정해진 기능을 본다. E는 이름 없이 성능을 단정하는 말을 본다.
# 예: "세탁 후에도 형태가 유지됩니다", "뛰어난 내구성", "열기를 효과적으로 방출", "숙면을 보장"
# ---------------------------------------------------------------------------
PERFORMANCE_PATTERNS: list[tuple[str, str]] = [
    ("내구성", r"내구성"),
    ("수명 연장", r"수명"),
    ("성능", r"성능"),
    ("효과", r"효과"),
    ("보장", r"보장"),
    ("문제 해소·개선", r"해소|개선"),
    ("세정력", r"세정력"),
    ("세탁 후 유지", r"세탁\s*(?:후|해도|하여도)[^.!?]{0,25}유지"),
    ("변형·변색·기능 저하 없음", r"(?:변색되지|늘어나지|" + PERSISTENCE_VERBS[3:-1] + r")\s*않"),
    ("밀림 방지", r"밀리지\s*않|안\s*밀|미끄럼\s*방지"),
    ("보습", r"보습|수분을\s*유지"),
]


def _check_performance(product: dict, content: dict) -> list[dict]:
    texts = _collect_texts(content) + _claim_texts(content)
    approved = _norm(" ".join(product.get("approved_claims") or []))
    notes = _split_sentences(product.get("source_notes", ""))

    def supported(written: str, pattern: str) -> bool:
        # 승인된 기능 목록에 같은 말이 있거나, 원본 메모에 '부정하지 않은' 형태로 있으면 입증된 주장으로 본다.
        # ("내구성 시험은 하지 않았음" 같은 메모는 근거가 아니다.)
        if _norm(written) in approved:
            return True
        return any(not _is_negated(note, m.end()) for note in notes for m in re.finditer(pattern, note))

    flags: list[dict] = []
    reported: set[tuple[str, str]] = set()
    for name, pattern in PERFORMANCE_PATTERNS:
        for text_field, sentence in texts:
            if (name, text_field) in reported:
                continue
            match = re.search(pattern, sentence)
            if match is None or supported(match.group(0), pattern):
                continue
            reported.add((name, text_field))
            flags.append(_flag(
                "E", "unsupported_performance",
                f"근거 자료에 없는 성능·효과 단정('{match.group(0)}')이 {field_label(text_field)}에 있습니다.",
                field=text_field, source_value=", ".join(product.get("approved_claims") or []),
                generated_value=match.group(0), evidence=sentence,
            ))
    return flags


# ---------------------------------------------------------------------------
# 기준 C: 필수 정보 누락
# ---------------------------------------------------------------------------
FIELD_LABELS = {"material": "소재", "colors": "색상", "sizes": "사이즈", "care_instructions": "관리 방법"}


def _check_required(product: dict, content: dict | None) -> list[dict]:
    category = product.get("category", "")
    required = config.REQUIRED_FIELDS_BY_CATEGORY.get(category, config.REQUIRED_FIELDS_DEFAULT)
    flags: list[dict] = []
    for field in required:
        value = product.get(field)
        empty = not value or (isinstance(value, str) and not value.strip())
        if empty:
            label = FIELD_LABELS.get(field, field)
            flags.append(_flag("C", "required_missing", f"필수 정보 '{label}'이(가) 원본에 비어 있습니다.",
                               field=field))
    care_guide = (content or {}).get("care_guide") or ""
    if not str(product.get("care_instructions", "")).strip() and str(care_guide).strip():
        flags.append(_flag("C", "invented_care_guide", "AI가 원본에 없는 관리 방법을 임의로 작성했습니다.",
                           field="care_guide", generated_value=care_guide, evidence=care_guide))
    return flags


# ---------------------------------------------------------------------------
# 기준 D: 가격 불일치
# ---------------------------------------------------------------------------
def _extract_prices(text: str) -> list[dict]:
    """문장에서 가격 표현을 뽑는다. kind: exact(정확한 값) / range(○만 원대) / discount(할인 금액)."""
    found: list[dict] = []
    taken: list[tuple[int, int]] = []

    def add(value: float, is_range: bool, span: tuple[int, int], raw: str) -> None:
        after = text[span[1]:span[1] + 6].strip()
        if is_range:
            step = 10000 if "만" in raw else 10 ** max(len(str(int(value))) - 1, 0)
            found.append({"kind": "range", "low": int(value), "high": int(value) + step, "raw": raw})
        elif after.startswith(DISCOUNT_WORDS):
            found.append({"kind": "discount", "value": int(round(value)), "raw": raw})
        else:
            found.append({"kind": "exact", "value": int(round(value)), "raw": raw})

    for match in KOREAN_PRICE_RE.finditer(text):
        value = float(match.group(1)) * 10000 + (int(match.group(2)) * 1000 if match.group(2) else 0)
        taken.append(match.span())
        add(value, bool(match.group(3)), match.span(), match.group(0))
    for match in NUMBER_PRICE_RE.finditer(text):
        if any(match.start() < e and s < match.end() for s, e in taken):
            continue
        add(float(match.group(1).replace(",", "")), bool(match.group(2)), match.span(), match.group(0))
    return found


def _check_price(product: dict, content: dict) -> list[dict]:
    selling = product.get("selling_price")
    sale = product.get("sale_price")
    valid = [p for p in (selling, sale) if p]
    source_value = f"판매가 {selling or '-'} / 할인가 {sale or '-'}"
    texts = _collect_texts(content) + _claim_texts(content)
    if content.get("price_display"):
        texts.append(("price_display", str(content["price_display"])))

    flags: list[dict] = []
    for field, sentence in texts:
        for price in _extract_prices(sentence):
            if not valid:
                ok = False
            elif price["kind"] == "range":
                ok = any(price["low"] <= p < price["high"] for p in valid)
            elif price["kind"] == "discount":
                ok = bool(selling and sale) and price["value"] == selling - sale
            else:
                ok = price["value"] in valid
            if not ok:
                message = ("원본에 가격이 없는데 생성 문구에 가격이 있습니다." if not valid
                           else f"생성 문구의 가격 '{price['raw']}'이(가) 원본 가격과 다릅니다.")
                flags.append(_flag("D", "price_mismatch", message, field=field,
                                   source_value=source_value, generated_value=price["raw"], evidence=sentence))
        for regex in PERCENT_RES:
            for match in regex.finditer(sentence):
                stated = float(match.group(1))
                if selling and sale and sale < selling:
                    expected = int((selling - sale) / selling * 100 + 0.5)
                    if abs(stated - expected) < 1e-9:
                        continue
                    message = f"할인율 '{match.group(0)}'이(가) 원본 가격으로 계산한 {expected}%와 다릅니다."
                else:
                    message = f"원본에 할인 정보가 없는데 할인율 '{match.group(0)}'이(가) 있습니다."
                flags.append(_flag("D", "discount_mismatch", message, field=field,
                                   source_value=source_value, generated_value=match.group(0), evidence=sentence))
                break
    return flags


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
def validate(
    product: dict,
    content: dict | None,
    rules: Iterable[str] = config.ACTIVE_RULES,
    *,
    negation_guard: bool = True,
) -> list[dict]:
    """검증 결과(문제 목록)를 돌려준다. 빈 목록이면 자동 게시해도 된다는 뜻이다.

    기준 S(출력 구조)는 rules와 상관없이 항상 검사한다.
    """
    active = set(rules)
    structure_flags = _check_structure(content)
    if structure_flags:
        # 구조가 깨진 콘텐츠는 문장을 읽을 수 없으니, 원본만 보는 필수 정보 검사만 덧붙인다.
        extra = _check_required(product, None) if "C" in active else []
        return structure_flags + extra

    flags: list[dict] = []
    if "A" in active:
        flags.extend(_check_core_info(product, content))
    if "B" in active:
        flags.extend(_check_claims(product, content, negation_guard))
    if "C" in active:
        flags.extend(_check_required(product, content))
    if "D" in active:
        flags.extend(_check_price(product, content))
    if "E" in active:
        flags.extend(_check_performance(product, content))
    return flags
