"""LangGraph 그래프 조립과 체크포인터 연결.

흐름:
  prepare_product → generate_content → (실패) mark_failed → finish
                                     → validate_content → (통과) publish_to_demo_catalog → finish
                                                        → (문제) mark_pending → human_review
  human_review → approve            → publish_to_demo_catalog
               → approve_with_edits → apply_human_edits → validate_content
               → reassess           → regenerate_content → validate_content (실패 시 mark_failed)
               → reject             → reject_request → finish
               → 잘못된 응답        → record_review_error → human_review (다시 멈춤)

체크포인터는 SQLite 파일에 저장되므로 앱을 다시 켜도 멈춘 지점에서 이어 갈 수 있다.
"""
from __future__ import annotations

import sqlite3
import threading
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from src import config, nodes

_lock = threading.Lock()
_app = None
_conn: Optional[sqlite3.Connection] = None


def build_graph() -> StateGraph:
    """처리 단계와 연결선을 등록한 그래프(컴파일 전)를 만든다."""
    graph = StateGraph(nodes.GraphState)

    graph.add_node("prepare_product", nodes.prepare_product)
    graph.add_node("generate_content", nodes.generate_content)
    graph.add_node("validate_content", nodes.validate_content)
    graph.add_node("mark_pending", nodes.mark_pending)
    graph.add_node("human_review", nodes.human_review)
    graph.add_node("record_review_error", nodes.record_review_error)
    graph.add_node("apply_human_edits", nodes.apply_human_edits)
    graph.add_node("regenerate_content", nodes.regenerate_content)
    graph.add_node("publish_to_demo_catalog", nodes.publish_to_demo_catalog)
    graph.add_node("reject_request", nodes.reject_request)
    graph.add_node("mark_failed", nodes.mark_failed)
    graph.add_node("finish", nodes.finish)

    graph.add_edge(START, "prepare_product")
    graph.add_edge("prepare_product", "generate_content")
    graph.add_conditional_edges(
        "generate_content", nodes.route_after_generation, ["validate_content", "mark_failed"]
    )
    graph.add_conditional_edges(
        "validate_content", nodes.route_after_validation, ["publish_to_demo_catalog", "mark_pending"]
    )
    graph.add_edge("mark_pending", "human_review")
    graph.add_conditional_edges(
        "human_review",
        nodes.route_after_review,
        ["publish_to_demo_catalog", "apply_human_edits", "regenerate_content", "reject_request", "record_review_error"],
    )
    graph.add_edge("record_review_error", "human_review")
    graph.add_edge("apply_human_edits", "validate_content")
    graph.add_conditional_edges(
        "regenerate_content", nodes.route_after_generation, ["validate_content", "mark_failed"]
    )
    graph.add_edge("publish_to_demo_catalog", "finish")
    graph.add_edge("reject_request", "finish")
    graph.add_edge("mark_failed", "finish")
    graph.add_edge("finish", END)
    return graph


def get_app():
    """프로세스 전체에서 같이 쓰는 컴파일된 그래프를 돌려준다."""
    global _app, _conn
    with _lock:
        if _app is None:
            _conn = sqlite3.connect(config.checkpoint_db_path(), check_same_thread=False)
            saver = SqliteSaver(_conn)
            saver.setup()
            _app = build_graph().compile(checkpointer=saver)
        return _app


def reset_app_cache() -> None:
    """캐시한 그래프와 체크포인트 연결을 버린다(테스트·재시작 확인용)."""
    global _app, _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _app = None
        _conn = None


def thread_config(thread_id: str) -> dict:
    """요청마다 다른 thread_id로 체크포인트를 나눈다."""
    return {"configurable": {"thread_id": thread_id}}
