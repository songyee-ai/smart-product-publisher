"""승인 기준 조합별 평가: 몇 건을 멈추는지, 무엇을 놓치고 무엇을 괜히 멈추는지 센다.

- 멈춤(stopped): 사람 승인으로 보낸 건수
- 미탐(missed): 사람이 봐야 하는데(expected=True) 자동 게시된 건수
- 오탐(false stop): 바로 게시해도 되는데(expected=False) 멈춘 건수
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from src.generation import generate_content
from src.sample_data import SAMPLES
from src.validation import validate

# 로컬 LLM이 실제로 쓴 출력과 정답 라벨 (다시 생성하지 않고 저장된 출력을 그대로 검증한다)
# - llm: 기준 E를 만들 때 참고한 출력 20건
# - holdout: 기준을 고친 뒤 새로 생성해, 규칙을 돌리기 전에 라벨을 붙인 출력 20건
EVAL_DATA_DIR = Path(__file__).resolve().parent / "eval_data"
REPLAY_FILES = {"llm": "llm_replay.json", "holdout": "llm_holdout.json"}

CRITERIA_COMBOS: list[dict] = [
    {"key": "none", "label": "기준 없음 (구조 오류만 멈춤)", "rules": [], "negation_guard": True, "baseline": True},
    {"key": "A", "label": "기준 A만", "rules": ["A"], "negation_guard": True},
    {"key": "AB", "label": "A+B", "rules": ["A", "B"], "negation_guard": True},
    {"key": "ABC", "label": "A+B+C", "rules": ["A", "B", "C"], "negation_guard": True},
    {"key": "ABCD_noneg", "label": "A+B+C+D (부정문 예외 없음)", "rules": ["A", "B", "C", "D"],
     "negation_guard": False},
    {"key": "ABCD", "label": "A+B+C+D", "rules": ["A", "B", "C", "D"], "negation_guard": True},
    {"key": "ABCDE", "label": "A+B+C+D+E (최종)", "rules": ["A", "B", "C", "D", "E"],
     "negation_guard": True},
    {"key": "all", "label": "전부 멈춤 (모두 사람 승인)", "rules": ["A", "B", "C", "D"], "negation_guard": True,
     "baseline": True, "stop_all": True},
]


@lru_cache(maxsize=None)
def load_llm_replay(dataset: str = "llm") -> list[dict]:
    """저장된 LLM 출력 평가 데이터를 읽는다."""
    with open(EVAL_DATA_DIR / REPLAY_FILES[dataset], encoding="utf-8") as file:
        return json.load(file)["items"]


def _judge(combo: dict, product: dict, content: dict) -> tuple[bool, list[dict]]:
    flags = validate(product, content, rules=combo["rules"], negation_guard=combo["negation_guard"])
    # '전부 멈춤' 기준선은 검증 결과와 상관없이 항상 사람 승인으로 보낸다.
    actual = True if combo.get("stop_all") else bool(flags)
    return actual, flags


def _summarize(combo: dict, rows: list[dict]) -> dict:
    """판정 행 목록을 개입률·놓침·헛멈춤으로 집계한다."""
    missed_ids = [r["sample_id"] for r in rows if r["expected"] and not r["actual"]]
    false_stop_ids = [r["sample_id"] for r in rows if r["actual"] and not r["expected"]]
    stopped = sum(1 for r in rows if r["actual"])
    total = len(rows)
    return {
        "key": combo["key"],
        "label": combo["label"],
        "total": total,
        "stopped": stopped,
        "intervention_rate": round(stopped / total * 100, 1) if total else 0.0,
        "missed": len(missed_ids),
        "false_stops": len(false_stop_ids),
        "missed_ids": missed_ids,
        "false_stop_ids": false_stop_ids,
        "rows": rows,
    }


def evaluate_combo(combo: dict, samples: list[dict] = SAMPLES) -> dict:
    """기준 조합 하나로 고정 샘플 전체를 판정하고 집계한다."""
    rows = []
    for sample in samples:
        product = sample["product"]
        content = generate_content(product, mode="sample", sample_id=sample["sample_id"])
        actual, flags = _judge(combo, product, content)
        rows.append({
            "sample_id": sample["sample_id"],
            "title": sample["title"],
            "expected": bool(sample["expected_review"]),
            "actual": actual,
            "flags_rules": sorted({flag["rule"] for flag in flags}),
        })
    return _summarize(combo, rows)


def evaluate_replay(combo: dict, dataset: str = "llm") -> dict:
    """기준 조합 하나로 저장된 LLM 실제 출력을 판정하고 집계한다."""
    rows = []
    for item in load_llm_replay(dataset):
        actual, flags = _judge(combo, item["product"], item["content"])
        rows.append({
            "sample_id": item["item_id"],
            "title": item["product"]["product_name"],
            "expected": bool(item["expected_review"]),
            "actual": actual,
            "flags_rules": sorted({flag["rule"] for flag in flags}),
        })
    return _summarize(combo, rows)


def evaluate_all(dataset: str = "samples") -> list[dict]:
    """모든 기준 조합의 평가 결과 (항상 같은 결과가 나온다).

    dataset="samples": 고정 샘플 20건
    dataset="llm": 기준 E를 만들 때 참고한 LLM 출력 20건
    dataset="holdout": 기준을 고친 뒤 새로 받은 LLM 출력 20건 (처음 보는 데이터)
    """
    if dataset in REPLAY_FILES:
        return [evaluate_replay(combo, dataset) for combo in CRITERIA_COMBOS]
    return [evaluate_combo(combo) for combo in CRITERIA_COMBOS]


def print_tables() -> None:
    """세 평가 데이터의 기준 조합 비교표를 터미널에 출력한다."""
    titles = {
        "samples": "고정 샘플 20건",
        "llm": "LLM 실제 출력 20건 (기준 E를 만들 때 참고)",
        "holdout": "LLM 실제 출력 20건 (처음 보는 데이터)",
    }
    for dataset, title in titles.items():
        print(f"\n[{title}]")
        print(f"{'기준 조합':<34}{'멈춤':>8}{'개입률':>9}{'놓침':>6}{'헛멈춤':>7}")
        for result in evaluate_all(dataset):
            print(f"{result['label']:<34}{result['stopped']:>5}/{result['total']:<3}"
                  f"{result['intervention_rate']:>7.1f}%{result['missed']:>6}{result['false_stops']:>7}")


if __name__ == "__main__":
    print_tables()
