"""Email Summarizer Agent — generates TL;DR, key points, and action items.

Uses Google Gemini to analyze email content and extract structured information.
"""

from __future__ import annotations

import json

import structlog
from app.agents.llm_factory import get_llm

logger = structlog.get_logger()

SUMMARIZER_PROMPT = """
Analyze the following email and provide a structured summary.
Extract the TL;DR, key points, action items, sentiment, and any mentions of deadlines.

Email Details:
From: {sender_name} <{sender}>
Subject: {subject}
Received: {received_at}

Content:
{body_text}

Return your analysis as a JSON object strictly following this schema:
{{
    "tldr": "one-sentence summary",
    "key_points": ["point 1", "point 2", ...],
    "action_items": ["item 1", "item 2", ...],
    "sentiment": "positive" | "neutral" | "negative",
    "deadlines": ["deadline 1", ...]
}}
"""

async def summarize_email(email_data: dict) -> dict:
    """Summarize an email using Google Gemini."""
    llm = get_llm(temperature=0.2, max_tokens=500)

    body_text = (email_data.get("body_text") or "")[:5000]

    prompt = SUMMARIZER_PROMPT.format(
        sender=email_data.get("sender", "Unknown"),
        sender_name=email_data.get("sender_name", "Unknown"),
        subject=email_data.get("subject", "(no subject)"),
        received_at=email_data.get("received_at", "Unknown"),
        body_text=body_text or "(empty body)",
    )

    try:
        response = await llm.ainvoke(prompt)
        content = response.content.strip()

        # Clean potential markdown wrapping
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(content)

        summary = {
            "tldr": str(result.get("tldr", "No summary available"))[:500],
            "key_points": [str(p)[:200] for p in result.get("key_points", [])][:5],
            "action_items": [str(a)[:200] for a in result.get("action_items", [])][:5],
            "sentiment": str(result.get("sentiment", "neutral"))[:20],
            "deadlines": [str(d)[:100] for d in result.get("deadlines", [])][:5],
        }

        logger.info(
            "email_summarized",
            subject=email_data.get("subject", "")[:50],
            key_points_count=len(summary["key_points"]),
            action_items_count=len(summary["action_items"]),
        )
        return summary

    except json.JSONDecodeError as e:
        logger.error("summarizer_json_parse_error", error=str(e))
        return {
            "tldr": "Summary generation failed.",
            "key_points": [],
            "action_items": [],
            "sentiment": "neutral",
            "deadlines": [],
        }
    except Exception as e:
        logger.error("summarizer_error", error=str(e))
        return {
            "tldr": f"Summary error: {str(e)[:100]}",
            "key_points": [],
            "action_items": [],
            "sentiment": "neutral",
            "deadlines": [],
        }
