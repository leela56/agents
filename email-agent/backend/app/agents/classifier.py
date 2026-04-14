"""Email Classifier Agent — categorizes emails using Google Gemini.

Categories:
- urgent: Needs immediate action (deadlines, critical issues)
- action_required: Needs response but not urgent
- informational: FYI, newsletters, notifications
- spam: Promotions, marketing, junk
"""

from __future__ import annotations

import json

import structlog
from app.agents.llm_factory import get_llm

from app.database import EmailCategory

logger = structlog.get_logger()

CLASSIFIER_PROMPT = """
Analyze the following email and categorize it into exactly one of these categories:
- urgent: Needs immediate action (deadlines, critical business issues)
- action_required: Needs a response or action but is not time-critical
- informational: FYIs, newsletters, meeting invites, or notifications
- spam: Marketing, promotions, or junk

Email Details:
From: {sender_name} <{sender}>
Subject: {subject}
Received: {received_at}

Content:
{body_preview}

Return your analysis as a JSON object strictly following this schema:
{{
    "category": "urgent" | "action_required" | "informational" | "spam",
    "confidence": float (0.0 to 1.0),
    "reasoning": "brief explanation"
}}
"""

async def classify_email(email_data: dict) -> dict:
    """Classify an email using Google Gemini."""
    llm = get_llm(temperature=0.1, max_tokens=200)

    body_preview = (email_data.get("body_text") or "")[:2000]

    prompt = CLASSIFIER_PROMPT.format(
        sender=email_data.get("sender", "Unknown"),
        sender_name=email_data.get("sender_name", "Unknown"),
        subject=email_data.get("subject", "(no subject)"),
        received_at=email_data.get("received_at", "Unknown"),
        body_preview=body_preview or "(empty body)",
    )

    try:
        response = await llm.ainvoke(prompt)
        
        if isinstance(response.content, list):
            content_parts = [str(part["text"]) for part in response.content if isinstance(part, dict) and "text" in part]
            content = "\n".join(content_parts).strip()
        else:
            content = str(response.content).strip()

        # Clean potential markdown wrapping
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(content)

        # Validate category
        category = result.get("category", "uncategorized")
        if category not in [e.value for e in EmailCategory]:
            category = "uncategorized"

        # Validate confidence
        confidence = float(result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        classification = {
            "category": category,
            "confidence": confidence,
            "reasoning": str(result.get("reasoning", ""))[:500],
        }

        logger.info(
            "email_classified",
            subject=email_data.get("subject", "")[:50],
            category=classification["category"],
            confidence=classification["confidence"],
        )
        return classification

    except json.JSONDecodeError as e:
        logger.error("classifier_json_parse_error", error=str(e), raw_content=content[:200])
        return {
            "category": EmailCategory.UNCATEGORIZED.value,
            "confidence": 0.0,
            "reasoning": "Classification failed — could not parse LLM response",
        }
    except Exception as e:
        logger.error("classifier_error", error=str(e))
        return {
            "category": EmailCategory.UNCATEGORIZED.value,
            "confidence": 0.0,
            "reasoning": f"Classification error: {str(e)[:100]}",
        }
