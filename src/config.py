"""환경변수와 공통 설정값.

설정은 한곳에 모아 두고, 다른 모듈은 여기서 가져다 쓴다.
`.env` 파일이 있으면 읽고, 없으면 기본값으로 동작한다(API 키가 필요 없다).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 프로젝트 루트(이 파일의 한 단계 위 폴더)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def data_dir() -> Path:
    """업무 DB와 체크포인트 DB를 둘 폴더. 테스트에서는 환경변수로 임시 폴더를 지정한다."""
    raw = os.getenv("SPP_DATA_DIR", "data")
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_db_path() -> Path:
    """요청·이력·데모 카탈로그를 저장하는 업무 DB 파일."""
    return data_dir() / "app.db"


def checkpoint_db_path() -> Path:
    """LangGraph 체크포인트(멈춘 지점)를 저장하는 DB 파일."""
    return data_dir() / "checkpoints.db"


# 생성 모드: "sample"(결정론적 샘플) 또는 "ollama"(로컬 LLM)
DEFAULT_GENERATION_MODE = os.getenv("GENERATION_MODE", "sample")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))

# 반복 상한: 다시 판정(재생성)과 수정 후 승인을 무한히 반복하지 않도록 막는다.
MAX_REGENERATIONS = 2
MAX_EDIT_ROUNDS = 2

# 운영 규칙: 승인 대기가 이 일수를 넘으면 '지연'으로 표시하고 대기함 맨 위로 올린다.
# 지연 건도 자동 승인하지 않는다.
OVERDUE_DAYS = 3

# 기준 C(필수 정보 누락)에서 검사할 필드. 카테고리별로 다르게 둘 수 있다.
REQUIRED_FIELDS_DEFAULT = ["material", "colors", "sizes", "care_instructions"]
REQUIRED_FIELDS_BY_CATEGORY: dict[str, list[str]] = {
    "침구": ["material", "colors", "sizes", "care_instructions"],
    "커튼": ["material", "colors", "sizes", "care_instructions"],
    "러그": ["material", "colors", "sizes", "care_instructions"],
}

# 승인 기준 이름 (화면·보고서 공통 표기)
RULE_NAMES = {
    "A": "핵심 상품 정보 불일치",
    "B": "근거 없는 기능·효능·인증 표현",
    "C": "필수 상품 정보 누락",
    "D": "가격 정보 불일치",
    "E": "근거 없는 성능·효과 단정",
    "S": "출력 구조 오류",
}

# 최종 운영에 쓰는 기준 조합
ACTIVE_RULES = ("A", "B", "C", "D", "E")
