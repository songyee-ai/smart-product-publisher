"""기준 조합 평가표 테스트. 숫자는 라벨과 판정 결과에서 다시 계산해 맞는지 확인한다."""
from __future__ import annotations

import pytest

from src.metrics import CRITERIA_COMBOS, evaluate_all, evaluate_combo
from src.sample_data import SAMPLES


@pytest.fixture(autouse=True)
def _tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPP_DATA_DIR", str(tmp_path))


@pytest.fixture(scope="module")
def results() -> dict:
    return {row["key"]: row for row in evaluate_all()}


def test_required_combos_exist():
    keys = {combo["key"] for combo in CRITERIA_COMBOS}
    assert {"none", "A", "AB", "ABCD_noneg", "ABCD", "all"} <= keys
    baselines = {combo["key"] for combo in CRITERIA_COMBOS if combo.get("baseline")}
    assert baselines == {"none", "all"}


def test_counts_are_internally_consistent(results):
    expected_true = sum(1 for s in SAMPLES if s["expected_review"])
    for row in results.values():
        rows = row["rows"]
        assert row["total"] == len(SAMPLES) == len(rows)
        assert row["stopped"] == sum(r["actual"] for r in rows)
        assert row["missed_ids"] == [r["sample_id"] for r in rows if r["expected"] and not r["actual"]]
        assert row["false_stop_ids"] == [r["sample_id"] for r in rows if r["actual"] and not r["expected"]]
        assert row["missed"] == len(row["missed_ids"])
        assert row["false_stops"] == len(row["false_stop_ids"])
        assert row["intervention_rate"] == round(row["stopped"] / row["total"] * 100, 1)
        # 맞게 멈춘 건 + 놓친 건 = 사람이 봐야 할 건
        hits = sum(1 for r in rows if r["expected"] and r["actual"])
        assert hits + row["missed"] == expected_true
        assert row["stopped"] == hits + row["false_stops"]


def test_rows_follow_labels(results):
    labels = {s["sample_id"]: s["expected_review"] for s in SAMPLES}
    for row in results.values():
        for r in row["rows"]:
            assert r["expected"] == labels[r["sample_id"]]


def test_baselines(results):
    expected_true = sum(1 for s in SAMPLES if s["expected_review"])
    expected_false = len(SAMPLES) - expected_true
    assert results["none"]["stopped"] == 0
    assert results["none"]["missed"] == expected_true
    assert results["all"]["missed"] == 0
    assert results["all"]["stopped"] == len(SAMPLES)
    assert results["all"]["false_stops"] == expected_false
    assert results["all"]["intervention_rate"] == 100.0


def test_final_combo_honestly_misses_paraphrase(results):
    final = results["ABCDE"]
    assert final["missed"] >= 1
    assert "S11" in final["missed_ids"]  # "세균 걱정 없는" — 키워드 없는 바꿔 말하기


def test_negation_guard_reduces_false_stops(results):
    assert "S13" in results["ABCD_noneg"]["false_stop_ids"]  # "방수 기능은 없으니 ..."
    assert "S13" not in results["ABCD"]["false_stop_ids"]
    assert results["ABCD"]["false_stops"] < results["ABCD_noneg"]["false_stops"]


def test_adding_rules_never_increases_misses(results):
    order = ["none", "A", "AB", "ABC", "ABCD"]
    misses = [results[key]["missed"] for key in order]
    assert misses == sorted(misses, reverse=True)


def test_final_beats_single_rule(results):
    assert results["ABCD"]["missed"] < results["A"]["missed"]


def test_evaluation_is_deterministic():
    assert evaluate_all() == evaluate_all()


def test_evaluate_combo_with_subset():
    subset = [s for s in SAMPLES if s["sample_id"] in ("S01", "S02")]
    combo = next(c for c in CRITERIA_COMBOS if c["key"] == "A")
    row = evaluate_combo(combo, samples=subset)
    assert row["total"] == 2
    assert row["stopped"] == 1
    assert row["missed"] == 0 and row["false_stops"] == 0
    assert row["rows"][1]["flags_rules"] == ["A"]


# ---------------------------------------------------------------------------
# 저장된 LLM 실제 출력 재현 평가
# ---------------------------------------------------------------------------
def test_llm_replay_has_20_labeled_items():
    from src.metrics import load_llm_replay
    items = load_llm_replay()
    assert len(items) == 20
    assert all(isinstance(i["expected_review"], bool) and i["expected_reason"] for i in items)


def test_llm_replay_evaluation_is_deterministic():
    from src.metrics import evaluate_all
    first = [(r["key"], r["stopped"], r["missed"], r["false_stops"]) for r in evaluate_all("llm")]
    second = [(r["key"], r["stopped"], r["missed"], r["false_stops"]) for r in evaluate_all("llm")]
    assert first == second


def test_rule_e_adds_no_false_stop_on_fixed_samples():
    """E를 더해도 고정 샘플의 헛멈춤이 늘지 않아야 한다."""
    from src.metrics import CRITERIA_COMBOS, evaluate_combo
    by_key = {c["key"]: c for c in CRITERIA_COMBOS}
    abcd = evaluate_combo(by_key["ABCD"])
    abcde = evaluate_combo(by_key["ABCDE"])
    assert abcde["false_stops"] <= abcd["false_stops"]
    assert abcde["missed"] <= abcd["missed"]


def test_holdout_data_is_separate_and_labeled():
    from src.metrics import load_llm_replay
    holdout = load_llm_replay("holdout")
    assert len(holdout) == 20
    assert all(item["item_id"].startswith("H") for item in holdout)
    # 처음 보는 데이터는 기준을 만들 때 쓴 출력과 다른 문구여야 한다.
    dev_texts = {i["content"]["detail_description"] for i in load_llm_replay("llm")}
    assert not any(i["content"]["detail_description"] in dev_texts for i in holdout)


def test_final_combo_matches_config_active_rules():
    from src.config import ACTIVE_RULES
    from src.metrics import CRITERIA_COMBOS
    final = next(c for c in CRITERIA_COMBOS if "(최종)" in c["label"])
    assert tuple(final["rules"]) == tuple(ACTIVE_RULES)
