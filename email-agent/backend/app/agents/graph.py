"""LangGraph Workflow — orchestrates the email processing pipeline.

Flow: START → Classify → Summarize → Draft (conditional) → END

The draft step only runs for emails classified as 'urgent' or 'action_required'.
State is passed between nodes carrying the email data and accumulated AI results.
"""

from __future__ import annotations

from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.agents.classifier import classify_email
from app.agents.draft_writer import draft_reply
from app.agents.summarizer import summarize_email
from app.database import DraftTone

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------
class EmailAgentState(TypedDict):
    """State passed through the LangGraph workflow."""

    # Input
    email_data: dict[str, Any]

    # Accumulated results
    classification: dict[str, Any] | None
    summary: dict[str, Any] | None
    draft: dict[str, Any] | None

    # Control
    should_draft: bool
    error: str | None


# ---------------------------------------------------------------------------
# Graph Nodes
# ---------------------------------------------------------------------------
async def classify_node(state: EmailAgentState) -> dict:
    """Node 1: Classify the email."""
    logger.info("graph_node_classify", subject=state["email_data"].get("subject", "")[:50])

    try:
        classification = await classify_email(state["email_data"])
        # Determine if we should generate a draft
        should_draft = classification["category"] in ("urgent", "action_required")
        return {
            "classification": classification,
            "should_draft": should_draft,
        }
    except Exception as e:
        logger.error("graph_classify_error", error=str(e))
        return {
            "classification": {"category": "uncategorized", "confidence": 0.0, "reasoning": str(e)},
            "should_draft": False,
            "error": f"Classification failed: {str(e)}",
        }


async def summarize_node(state: EmailAgentState) -> dict:
    """Node 2: Summarize the email."""
    logger.info("graph_node_summarize", subject=state["email_data"].get("subject", "")[:50])

    try:
        summary = await summarize_email(state["email_data"])
        return {"summary": summary}
    except Exception as e:
        logger.error("graph_summarize_error", error=str(e))
        return {
            "summary": {"tldr": "Summary unavailable", "key_points": [], "action_items": [], "sentiment": "neutral", "deadlines": []},
            "error": f"Summarization failed: {str(e)}",
        }


async def draft_node(state: EmailAgentState) -> dict:
    """Node 3: Generate a reply draft (only for actionable emails)."""
    logger.info("graph_node_draft", subject=state["email_data"].get("subject", "")[:50])

    try:
        summary_text = state["summary"]["tldr"] if state.get("summary") else ""
        action_items = state["summary"].get("action_items", []) if state.get("summary") else []

        draft = await draft_reply(
            email_data=state["email_data"],
            summary=summary_text,
            action_items=action_items,
            tone=DraftTone.PROFESSIONAL,
        )
        return {"draft": draft}
    except Exception as e:
        logger.error("graph_draft_error", error=str(e))
        return {
            "draft": {"draft": "Draft unavailable", "tone": "professional", "suggested_subject": ""},
            "error": f"Draft generation failed: {str(e)}",
        }


# ---------------------------------------------------------------------------
# Conditional Edges
# ---------------------------------------------------------------------------
def should_generate_draft(state: EmailAgentState) -> str:
    """Decide whether to draft a reply or skip to END."""
    if state.get("should_draft", False):
        return "draft"
    return "end"


# ---------------------------------------------------------------------------
# Build Graph
# ---------------------------------------------------------------------------
def build_email_agent_graph() -> StateGraph:
    """Build the LangGraph workflow for email processing.

    Flow:
        START → classify → summarize → (if actionable) → draft → END
                                      → (if not actionable) → END
    """
    graph = StateGraph(EmailAgentState)

    # Add nodes
    graph.add_node("classify", classify_node)
    graph.add_node("summarize", summarize_node)
    graph.add_node("draft", draft_node)

    # Define edges
    graph.set_entry_point("classify")
    graph.add_edge("classify", "summarize")

    # Conditional: draft only for actionable emails
    graph.add_conditional_edges(
        "summarize",
        should_generate_draft,
        {
            "draft": "draft",
            "end": END,
        },
    )
    graph.add_edge("draft", END)

    return graph.compile()


# Singleton compiled graph
_compiled_graph = None


def get_email_agent_graph():
    """Get the compiled email agent graph (singleton)."""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_email_agent_graph()
        logger.info("langgraph_compiled")
    return _compiled_graph
