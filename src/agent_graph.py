"""
Agent métier robuste avec LangGraph.

Objectif atelier :
- récupérer une question utilisateur ;
- interroger Wikipedia ;
- router automatiquement vers :
  1) chemin standard si Wikipedia répond correctement ;
  2) chemin secours/DLQ si Wikipedia renvoie 404, 503, timeout, JSON invalide, etc.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict
from datetime import datetime, timezone
import hashlib
import os

import requests
from langgraph.graph import END, StateGraph

WIKIPEDIA_API_URL = os.getenv("WIKIPEDIA_API_URL", "https://en.wikipedia.org/w/api.php")
DLQ_API_URL = os.getenv("DLQ_API_URL", "http://127.0.0.1:3000/dlq/messages")
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "5"))


class AgentState(TypedDict, total=False):
    input_text: str
    prompt: str
    wiki_status_code: int | None
    wiki_payload: dict[str, Any] | None
    wiki_summary: str | None
    error: str | None
    route: Literal["standard", "dlq"]
    final_answer: str
    dlq_payload: dict[str, Any] | None
    dlq_status_code: int | None
    compliance: dict[str, Any]


def _correlation_id(text: str) -> str:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12].upper()
    return f"CID-{digest}"


def prepare_prompt(state: AgentState) -> AgentState:
    """Équivalent Prompt Node : prépare le contexte de réponse."""
    question = state.get("input_text", "").strip()
    if not question:
        return {
            **state,
            "prompt": "",
            "error": "EMPTY_INPUT",
            "route": "dlq",
        }

    prompt = (
        "You are a factual assistant. Answer using only verified Wikipedia context. "
        "If the external API fails, do not hallucinate; route to DLQ. "
        f"User question: {question}"
    )
    return {**state, "prompt": prompt}


def call_wikipedia(state: AgentState) -> AgentState:
    """Équivalent Wikipedia API Tool."""
    if state.get("route") == "dlq":
        return state

    question = state["input_text"].strip()
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "exintro": "true",
        "explaintext": "true",
        "titles": question.replace("Where ", "").replace("?", "").strip(),
        "redirects": "1",
    }

    try:
        response = requests.get(WIKIPEDIA_API_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        status_code = response.status_code
        if status_code != 200:
            return {
                **state,
                "wiki_status_code": status_code,
                "error": f"WIKIPEDIA_HTTP_{status_code}",
                "route": "dlq",
            }

        payload = response.json()
        pages = payload.get("query", {}).get("pages", {})
        if not pages:
            return {
                **state,
                "wiki_status_code": status_code,
                "wiki_payload": payload,
                "error": "WIKIPEDIA_NO_PAGES",
                "route": "dlq",
            }

        first_page = next(iter(pages.values()))
        if "missing" in first_page:
            return {
                **state,
                "wiki_status_code": status_code,
                "wiki_payload": payload,
                "error": "WIKIPEDIA_PAGE_MISSING",
                "route": "dlq",
            }

        extract = (first_page.get("extract") or "").strip()
        if not extract:
            return {
                **state,
                "wiki_status_code": status_code,
                "wiki_payload": payload,
                "error": "WIKIPEDIA_EMPTY_EXTRACT",
                "route": "dlq",
            }

        return {
            **state,
            "wiki_status_code": status_code,
            "wiki_payload": payload,
            "wiki_summary": extract,
            "route": "standard",
        }

    except requests.Timeout:
        return {**state, "error": "WIKIPEDIA_TIMEOUT", "route": "dlq"}
    except ValueError:
        return {**state, "error": "WIKIPEDIA_INVALID_JSON", "route": "dlq"}
    except requests.RequestException as exc:
        return {**state, "error": f"WIKIPEDIA_REQUEST_ERROR: {exc}", "route": "dlq"}


def smart_router(state: AgentState) -> Literal["standard", "dlq"]:
    """Équivalent Smart Router / Conditional Router."""
    return "standard" if state.get("route") == "standard" and state.get("wiki_summary") else "dlq"


def standard_answer(state: AgentState) -> AgentState:
    """Chemin Standard : génération réponse contrôlée sans hallucination."""
    summary = state.get("wiki_summary", "")
    short_summary = summary[:900].strip()
    answer = (
        f"Réponse basée sur Wikipedia : {short_summary}"
        if short_summary
        else "Aucune information fiable n'a été trouvée."
    )
    compliance = {
        "status": "SUCCESS",
        "route": "standard",
        "uses_external_source": True,
        "dlq_emitted": False,
        "no_hallucination_on_failure": True,
    }
    return {**state, "final_answer": answer, "compliance": compliance}


def post_to_dlq(state: AgentState) -> AgentState:
    """Chemin de secours : POST HTTP vers la quarantaine/DLQ."""
    payload = {
        "correlation_id": _correlation_id(state.get("input_text", "")),
        "original_prompt": state.get("input_text", ""),
        "status": "FAILED_ROUTED_TO_DLQ",
        "error": state.get("error", "UNKNOWN_ERROR"),
        "source": "wikipedia",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }

    dlq_status_code: int | None = None
    try:
        response = requests.post(DLQ_API_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        dlq_status_code = response.status_code
    except requests.RequestException:
        dlq_status_code = None

    compliance = {
        "status": "WARNING",
        "route": "dlq",
        "uses_external_source": False,
        "dlq_emitted": True,
        "no_hallucination_on_failure": True,
    }
    final_answer = (
        "Service externe indisponible. Votre demande a été placée en quarantaine technique "
        "pour analyse. Aucune réponse factuelle n'est générée afin d'éviter une hallucination."
    )
    return {
        **state,
        "dlq_payload": payload,
        "dlq_status_code": dlq_status_code,
        "final_answer": final_answer,
        "compliance": compliance,
    }


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("prompt_node", prepare_prompt)
    graph.add_node("wikipedia_api_tool", call_wikipedia)
    graph.add_node("standard_success_path", standard_answer)
    graph.add_node("api_request_dlq", post_to_dlq)

    graph.set_entry_point("prompt_node")
    graph.add_edge("prompt_node", "wikipedia_api_tool")
    graph.add_conditional_edges(
        "wikipedia_api_tool",
        smart_router,
        {
            "standard": "standard_success_path",
            "dlq": "api_request_dlq",
        },
    )
    graph.add_edge("standard_success_path", END)
    graph.add_edge("api_request_dlq", END)
    return graph.compile()


agent_graph = build_graph()


def run_agent(input_text: str) -> AgentState:
    """Fonction appelée par les tests et par l'API locale."""
    return agent_graph.invoke({"input_text": input_text})
