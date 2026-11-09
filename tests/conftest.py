"""테스트 공통 준비: 매 테스트마다 임시 폴더에 DB를 새로 만든다(data/ 폴더는 건드리지 않는다)."""
from __future__ import annotations

import pytest


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """임시 데이터 폴더를 쓰는 service 모듈."""
    monkeypatch.setenv("SPP_DATA_DIR", str(tmp_path))
    from src import graph, service

    graph.reset_app_cache()
    yield service
    graph.reset_app_cache()


@pytest.fixture
def sample_product():
    """샘플 ID로 원본 상품 정보를 꺼내는 함수."""
    from src.sample_data import get_sample

    def _get(sample_id: str) -> dict:
        return get_sample(sample_id)["product"]

    return _get


@pytest.fixture
def submit_sample(svc, sample_product):
    """샘플을 샘플 모드로 등록하는 함수."""

    def _submit(sample_id: str) -> dict:
        return svc.submit_product(sample_product(sample_id), mode="sample", sample_id=sample_id)

    return _submit
