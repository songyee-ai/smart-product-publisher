"""검증 규칙(A/B/C/D/S) 테스트."""
from __future__ import annotations

import pytest

from src.generation import apply_patch, build_clean_content
from src.validation import explain_rules, validate


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPP_DATA_DIR", str(tmp_path))


def make_product(**overrides) -> dict:
    product = {
        "product_id": "T-1",
        "product_name": "굿홈앤리빙 데일리 차렵이불",
        "category": "침구",
        "material": "면 100%",
        "colors": ["아이보리", "그레이"],
        "sizes": ["슈퍼싱글", "퀸"],
        "selling_price": 79000,
        "sale_price": 59000,
        "care_instructions": "30도 이하 미온수에 단독 세탁해 주세요.",
        "approved_claims": [],
        "source_notes": "구성: 이불 1장.",
    }
    product.update(overrides)
    return product


def content_with(product: dict, *sentences: str, **patch) -> dict:
    """깨끗한 템플릿에 문장을 덧붙인 콘텐츠."""
    spec = {"append_sentences": list(sentences)}
    spec.update(patch)
    return apply_patch(build_clean_content(product), spec, product)


def rules_of(flags) -> set[str]:
    return {flag["rule"] for flag in flags}


def codes_of(flags) -> set[str]:
    return {flag["code"] for flag in flags}


# ------------------------------------------------------------------ 기본
def test_clean_template_passes_all_rules():
    product = make_product()
    assert validate(product, build_clean_content(product)) == []


def test_flag_has_all_contract_keys():
    product = make_product()
    flags = validate(product, content_with(product, "극세사 원단입니다."))
    assert flags
    assert set(flags[0]) == {"rule", "code", "message", "field", "source_value", "generated_value", "evidence"}


def test_explain_rules_covers_every_letter():
    explanations = explain_rules()
    assert set(explanations) == {"A", "B", "C", "D", "E", "S"}
    from src.config import RULE_NAMES
    assert set(explanations) == set(RULE_NAMES)
    assert all(isinstance(text, str) and text for text in explanations.values())


# ------------------------------------------------------------------ S
def test_rule_s_none_content():
    flags = validate(make_product(), None, rules=[])
    assert rules_of(flags) == {"S"}


def test_rule_s_schema_error_even_without_rules():
    product = make_product()
    broken = build_clean_content(product)
    broken["selling_points"] = []
    broken["display_title"] = ""
    flags = validate(product, broken, rules=[])
    assert rules_of(flags) == {"S"}
    assert flags[0]["code"] == "schema_error"


def test_rule_s_not_dict():
    assert rules_of(validate(make_product(), "문자열", rules=["A"])) == {"S"}


def test_rule_s_negative_valid_content():
    product = make_product()
    assert validate(product, build_clean_content(product), rules=[]) == []


# ------------------------------------------------------------------ A
def test_rule_a_material_in_body_not_in_fact_claims():
    product = make_product(material="순면 100%")
    content = content_with(product, "극세사 원단이라 매끄러워요.")
    assert all("극세사" not in claim["claim"] for claim in content["fact_claims"])
    flags = validate(product, content, rules=["A"])
    assert codes_of(flags) == {"material_mismatch"}
    assert flags[0]["generated_value"] == "극세사"


def test_rule_a_material_in_fact_claims_only():
    product = make_product()
    content = build_clean_content(product)
    content["fact_claims"].append({"claim": "텐셀 소재", "claim_type": "material",
                                   "source_field": "", "source_value": ""})
    assert codes_of(validate(product, content, rules=["A"])) == {"material_mismatch"}


@pytest.mark.parametrize("phrase", ["순면 원단", "코튼 100% 원단", "100% 면 소재", "순면(코튼 100%)"])
def test_rule_a_synonym_normalization_cotton(phrase):
    product = make_product(material="면 100%")
    assert validate(product, content_with(product, f"{phrase}이라 부드러워요."), rules=["A"]) == []


def test_rule_a_cotton_blend_is_not_pure_cotton():
    product = make_product(material="면 60% 폴리에스터 40%")
    flags = validate(product, content_with(product, "순면 원단이라 부드러워요."), rules=["A"])
    assert codes_of(flags) == {"material_mismatch"}


def test_rule_a_microfiber_synonym():
    product = make_product(material="극세사(폴리에스터 100%)")
    assert validate(product, content_with(product, "마이크로화이바 원단입니다."), rules=["A"]) == []


def test_rule_a_color_positive_and_negative():
    product = make_product(colors=["아이보리", "베이지"])
    assert codes_of(validate(product, content_with(product, "은은한 크림색이에요."), rules=["A"])) == {
        "color_mismatch"}
    assert validate(product, content_with(product, "아이보리 색감이 은은해요."), rules=["A"]) == []


def test_rule_a_color_synonym():
    product = make_product(colors=["회색"])
    assert validate(product, content_with(product, "차분한 그레이 톤입니다."), rules=["A"]) == []


def test_rule_a_size_positive_and_negative():
    product = make_product(sizes=["슈퍼싱글", "퀸"])
    assert codes_of(validate(product, content_with(product, "킹 사이즈도 있어요."), rules=["A"])) == {
        "size_mismatch"}
    assert validate(product, content_with(product, "퀸 사이즈로 넉넉해요."), rules=["A"]) == []


def test_rule_a_super_single_is_not_single():
    product = make_product(sizes=["슈퍼싱글"])
    assert codes_of(validate(product, content_with(product, "싱글 침대에 맞아요."), rules=["A"])) == {
        "size_mismatch"}


def test_rule_a_large_king_does_not_cover_king():
    product = make_product(sizes=["라지킹"])
    assert codes_of(validate(product, content_with(product, "킹 사이즈입니다."), rules=["A"])) == {
        "size_mismatch"}


def test_rule_a_size_letters_in_source():
    product = make_product(sizes=["SS", "Q"])
    assert validate(product, content_with(product, "퀸 사이즈로 넉넉해요."), rules=["A"]) == []


def test_rule_a_size_word_inside_other_word_ignored():
    product = make_product(care_instructions="베이킹소다를 푼 물에 손세탁해 주세요.")
    assert validate(product, build_clean_content(product), rules=["A"]) == []


def test_rule_a_composition_positive_and_negative():
    product = make_product(source_notes="구성: 이불 1장, 베개커버 2장 포함.")
    assert validate(product, content_with(product, "베개커버 2장 포함 구성이에요."), rules=["A"]) == []
    product = make_product(source_notes="구성: 이불 1장.")
    flags = validate(product, content_with(product, "베개커버 2장 포함 구성이에요."), rules=["A"])
    assert codes_of(flags) == {"composition_unverified"}


def test_rule_a_composition_fact_claim():
    product = make_product(source_notes="구성: 이불 1장.")
    content = build_clean_content(product)
    content["fact_claims"].append({"claim": "4종 세트", "claim_type": "composition",
                                   "source_field": "", "source_value": ""})
    assert codes_of(validate(product, content, rules=["A"])) == {"composition_unverified"}


# ------------------------------------------------------------------ B
@pytest.mark.parametrize("sentence, family", [
    ("항균 기능으로 위생적이에요.", "항균"),
    ("알레르기 차단 효과가 있어요.", "알레르기"),
    ("방수 원단이라 안심이에요.", "방수"),
    ("발수 가공으로 물이 튕겨요.", "발수"),
    ("진드기 걱정 없는 이불이에요.", "진드기"),
    ("KC 인증을 받은 제품입니다.", "KC"),
    ("OEKO-TEX 인증 원단입니다.", "OEKO"),
    ("유해물질이 검출되지 않았습니다.", "유해"),
])
def test_rule_b_unsupported_keywords(sentence, family):
    product = make_product()
    flags = validate(product, content_with(product, sentence), rules=["B"])
    assert rules_of(flags) == {"B"}
    assert any(family.lower() in flag["message"].lower() for flag in flags)


def test_rule_b_supported_by_approved_claims():
    product = make_product(approved_claims=["항균 가공 원단 사용(시험성적서 보유)"])
    assert validate(product, content_with(product, "항균 가공 원단으로 만들었어요."), rules=["B"]) == []


def test_rule_b_supported_by_source_notes():
    product = make_product(source_notes="겉감에 발수 코팅 적용(시험성적서 보유).")
    assert validate(product, content_with(product, "발수 코팅이 되어 있어요."), rules=["B"]) == []


def test_rule_b_negated_source_note_is_not_support():
    product = make_product(source_notes="방수 기능은 없습니다.")
    flags = validate(product, content_with(product, "방수 원단입니다."), rules=["B"])
    assert rules_of(flags) == {"B"}


def test_rule_b_negation_guard_on_and_off():
    product = make_product()
    content = content_with(product, "방수 기능은 없습니다.")
    assert validate(product, content, rules=["B"], negation_guard=True) == []
    assert rules_of(validate(product, content, rules=["B"], negation_guard=False)) == {"B"}


def test_rule_b_negation_guard_variants():
    product = make_product()
    for sentence in ("항균 가공을 하지 않았습니다.", "방수는 안 되니 주의해 주세요."):
        assert validate(product, content_with(product, sentence), rules=["B"]) == []


def test_rule_b_worry_free_is_not_negation():
    product = make_product()
    flags = validate(product, content_with(product, "방수 기능이 있어 음료를 쏟아도 걱정 없어요."), rules=["B"])
    assert rules_of(flags) == {"B"}


def test_rule_b_unsupported_function_fact_claim_without_keyword():
    product = make_product()
    content = build_clean_content(product)
    content["fact_claims"].append({"claim": "땀을 빠르게 말려 줌", "claim_type": "function",
                                   "source_field": "", "source_value": ""})
    assert codes_of(validate(product, content, rules=["B"])) == {"unsupported_function_claim"}


def test_rule_b_paraphrase_without_keyword_is_missed():
    # 키워드 없이 바꿔 말한 효능 주장은 규칙의 한계로 놓친다 (평가표에서 미탐으로 드러난다).
    product = make_product()
    assert validate(product, content_with(product, "세균 걱정 없는 위생적인 이불이에요."), rules=["B"]) == []


def test_rule_b_mood_words_pass():
    product = make_product()
    assert validate(product, content_with(product, "호텔 같은 포근한 분위기를 느껴 보세요.")) == []


# ------------------------------------------------------------------ C
def test_rule_c_missing_required_fields():
    product = make_product(care_instructions="", colors=[])
    flags = validate(product, build_clean_content(product), rules=["C"])
    assert {flag["field"] for flag in flags} == {"care_instructions", "colors"}


def test_rule_c_invented_care_guide():
    product = make_product(care_instructions="")
    content = build_clean_content(product)
    content["care_guide"] = "40도 물세탁 가능"
    assert "invented_care_guide" in codes_of(validate(product, content, rules=["C"]))


def test_rule_c_negative_and_default_category():
    product = make_product(category="주방용품")
    assert validate(product, build_clean_content(product), rules=["C"]) == []


def test_rule_c_still_checked_when_structure_broken():
    product = make_product(material="")
    assert rules_of(validate(product, None, rules=["C"])) == {"S", "C"}


# ------------------------------------------------------------------ D
@pytest.mark.parametrize("price_text", ["59,000원", "59000원", "5만 9천원", "5.9만원", "79,000원"])
def test_rule_d_price_formats_match(price_text):
    product = make_product()
    assert validate(product, content_with(product, f"지금 {price_text}에 만나 보세요."), rules=["D"]) == []


@pytest.mark.parametrize("price_text", ["49,000원", "69000원", "6만 9천원", "6.9만원"])
def test_rule_d_price_formats_mismatch(price_text):
    product = make_product()
    flags = validate(product, content_with(product, f"지금 {price_text}에 만나 보세요."), rules=["D"])
    assert codes_of(flags) == {"price_mismatch"}


def test_rule_d_price_display_mismatch():
    product = make_product()
    content = content_with(product, price_display="할인가 9,900원")
    assert codes_of(validate(product, content, rules=["D"])) == {"price_mismatch"}


def test_rule_d_no_source_price_any_price_flags():
    product = make_product(selling_price=None, sale_price=None)
    content = content_with(product, "단돈 39,000원!")
    assert codes_of(validate(product, content, rules=["D"])) == {"price_mismatch"}
    assert validate(product, build_clean_content(product), rules=["D"]) == []


def test_rule_d_price_range():
    product = make_product()
    assert validate(product, content_with(product, "5만 원대 가격이에요."), rules=["D"]) == []
    assert codes_of(validate(product, content_with(product, "6만 원대 가격이에요."), rules=["D"])) == {
        "price_mismatch"}


def test_rule_d_discount_percent():
    product = make_product()  # 79,000 → 59,000 = 25.3% → 25%
    assert validate(product, content_with(product, "정상가 대비 25% 할인!"), rules=["D"]) == []
    assert codes_of(validate(product, content_with(product, "정상가 대비 30% 할인!"), rules=["D"])) == {
        "discount_mismatch"}


def test_rule_d_discount_without_sale_price():
    product = make_product(sale_price=None)
    assert codes_of(validate(product, content_with(product, "20% 할인 중!"), rules=["D"])) == {
        "discount_mismatch"}


def test_rule_d_discount_amount():
    product = make_product()
    assert validate(product, content_with(product, "20,000원 할인된 가격이에요."), rules=["D"]) == []
    assert codes_of(validate(product, content_with(product, "30,000원 할인된 가격이에요."), rules=["D"])) == {
        "price_mismatch"}


def test_rule_d_percent_of_material_is_not_discount():
    product = make_product()
    assert validate(product, content_with(product, "면 100% 원단입니다."), rules=["D"]) == []


# ------------------------------------------------------------------ 기준 선택
def test_inactive_rules_are_not_checked():
    product = make_product(care_instructions="")
    content = content_with(product, "극세사 원단, 항균 기능, 단돈 9,900원!")
    assert validate(product, content, rules=[]) == []
    assert rules_of(validate(product, content)) == {"A", "B", "C", "D"}


# ---------------------------------------------------------------------------
# 로컬 LLM 시험 생성 뒤 보강한 부분
# ---------------------------------------------------------------------------
def test_same_word_in_two_fields_is_reported_for_each_field():
    """같은 단어라도 위치가 다르면 각각 보고해 담당자가 고칠 곳을 모두 본다."""
    product = make_product()
    content = content_with(product, "극세사 원단이라 매끄러워요.",
                           replace={"one_line_summary": "포근한 극세사 차렵이불"})
    messages = [f["message"] for f in validate(product, content) if f["code"] == "material_mismatch"]
    assert len(messages) == 2
    assert any("한 줄 요약" in m for m in messages)
    assert any("상세 설명" in m for m in messages)


def test_messages_use_korean_field_names():
    product = make_product()
    content = content_with(product, "항균 가공으로 위생적이에요.")
    message = next(f["message"] for f in validate(product, content) if f["rule"] == "B")
    assert "상세 설명" in message
    assert "detail_description" not in message


def test_composition_claim_without_count_is_not_flagged():
    """'면 100%로 구성됩니다'처럼 개수 없는 문장은 구성 주장으로 보지 않는다."""
    product = make_product()
    content = content_with(product, extra_claims=[
        {"claim": "면 100%로 구성됩니다", "claim_type": "composition",
         "source_field": "material", "source_value": "면 100%"},
    ])
    assert "composition_unverified" not in codes_of(validate(product, content))


def test_composition_claim_with_count_still_flagged():
    product = make_product()
    content = content_with(product, extra_claims=[
        {"claim": "베개커버 2장 포함", "claim_type": "composition",
         "source_field": "", "source_value": ""},
    ])
    assert "composition_unverified" in codes_of(validate(product, content))


@pytest.mark.parametrize("sentence", [
    "피부와 호흡기 건강에 좋은 소재예요.",
    "체온 조절 기능으로 여름에도 쾌적해요.",
    "방독 처리된 원단을 썼어요.",
])
def test_health_performance_claims_are_flagged(sentence):
    product = make_product()
    assert "B" in rules_of(validate(product, content_with(product, sentence)))


# ---------------------------------------------------------------------------
# 기준 E: 근거 없는 성능·효과 단정
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("sentence", [
    "세탁 후에도 부드럽고 단단하게 유지됩니다.",
    "뛰어난 내구성을 자랑합니다.",
    "열기를 효과적으로 방출합니다.",
    "완벽한 숙면을 보장해 드립니다.",
    "염색이 변하지 않고 오래갑니다.",
    "잘 안 밀려서 편해요.",
])
def test_rule_e_flags_unsupported_performance(sentence):
    product = make_product()
    flags = validate(product, content_with(product, sentence), rules=["E"])
    assert rules_of(flags) == {"E"}


def test_rule_e_off_by_default_combo_without_e():
    product = make_product()
    content = content_with(product, "뛰어난 내구성을 자랑합니다.")
    assert "E" not in rules_of(validate(product, content, rules=["A", "B", "C", "D"]))


def test_rule_e_allows_supported_performance():
    product = make_product(approved_claims=["세탁 후 형태 유지 시험 통과, 내구성 시험성적서 보유"])
    content = content_with(product, "뛰어난 내구성을 자랑합니다.")
    assert "E" not in rules_of(validate(product, content, rules=["E"]))


def test_rule_e_ignores_subjective_mood():
    product = make_product()
    content = content_with(product, "포근하고 차분한 분위기를 만들어 줘요. 호텔 같은 느낌이에요.")
    assert "E" not in rules_of(validate(product, content, rules=["E"]))


@pytest.mark.parametrize("sentence", ["피부에 자극 없이 부드러워요.", "수면 질을 높여 줍니다."])
def test_claim_patterns_tolerate_particles(sentence):
    product = make_product()
    assert "B" in rules_of(validate(product, content_with(product, sentence)))


# ---------------------------------------------------------------------------
# 독립 검증에서 찾은 우회 사례
# ---------------------------------------------------------------------------
def test_approved_claim_in_same_sentence_does_not_cover_other_claims():
    """승인 기능이 '항균'뿐이면 같은 문장의 '방수'는 여전히 걸려야 한다."""
    product = make_product(approved_claims=["항균"])
    flags = validate(product, content_with(product, "항균과 방수 기능을 모두 갖췄습니다."))
    assert any(f["rule"] == "B" and "방수" in f["message"] for f in flags)
    assert not any(f["rule"] == "B" and "'항균'" in f["message"] for f in flags)


@pytest.mark.parametrize("sentence", ["항균 기능이 줄지 않습니다.", "방수 처리가 벗겨지지 않아요."])
def test_persistence_claims_are_not_treated_as_negation(sentence):
    """'줄지 않습니다'는 기능을 부정하는 말이 아니라 오래간다는 주장이다."""
    product = make_product()
    assert "B" in rules_of(validate(product, content_with(product, sentence)))


def test_true_negation_still_passes():
    product = make_product()
    assert "B" not in rules_of(validate(product, content_with(product, "방수 기능은 없습니다.")))


def test_rule_e_ignores_negated_source_note():
    """'내구성 시험은 하지 않았음'은 내구성 주장의 근거가 아니다."""
    product = make_product(source_notes="구성: 이불 1장. 내구성 시험은 하지 않았음.")
    flags = validate(product, content_with(product, "뛰어난 내구성을 자랑합니다."), rules=["E"])
    assert rules_of(flags) == {"E"}


def test_rule_e_accepts_positive_source_note():
    product = make_product(source_notes="구성: 이불 1장. 내구성 시험 통과(성적서 보유).")
    flags = validate(product, content_with(product, "뛰어난 내구성을 자랑합니다."), rules=["E"])
    assert flags == []
