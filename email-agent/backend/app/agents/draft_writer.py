"""Draft Writer Agent — generates contextual email reply drafts.

Supports different tones (professional, friendly, brief) and
matches the formality level of the original email.
"""

from __future__ import annotations
import json
import structlog
from app.agents.llm_factory import get_llm

from app.database import DraftTone

logger = structlog.get_logger()

DRAFT_PROMPT = """
You are an expert AI email assistant. Your task is to draft a reply to the following email.

Email Details:
From: {sender_name} <{sender}>
Subject: {subject}

{body_text}

Context:
Summary: {summary}
Action Items:
{action_items}

Draft Instructions:
- Adopt a {tone} tone. {additional_instructions}

Return the draft as a JSON object strictly following this schema:
{{
    "draft": "The email reply body text",
    "suggested_subject": "Re: ..."
}}
"""

async def draft_reply(
    email_data: dict,
    summary: str,
    action_items: list[str],
    tone: DraftTone = DraftTone.PROFESSIONAL,
    additional_instructions: str | None = None,
) -> dict:

    llm = get_llm(temperature=0.5, max_tokens=1000)

    body_text = (email_data.get("body_text") or "")[:3000]
    action_items_str = "\n".join(f"- {item}" for item in (action_items or [])) or "None"
    extra = f"\nAdditional instructions: {additional_instructions}" if additional_instructions else ""

    prompt = DRAFT_PROMPT.format(
        sender=email_data.get("sender", "Unknown"),
        sender_name=email_data.get("sender_name", "Unknown"),
        subject=email_data.get("subject", "(no subject)"),
        body_text=body_text or "(empty body)",
        summary=summary or "No summary available",
        action_items=action_items_str,
        tone=tone.value,
        additional_instructions=extra,
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

        draft = {
            "draft": str(result.get("draft", ""))[:5000],
            "tone": tone.value,
            "suggested_subject": str(result.get("suggested_subject", f"Re: {email_data.get('subject', '')}"))[:200],
        }

        logger.info(
            "draft_generated",
            subject=email_data.get("subject", "")[:50],
            tone=tone.value,
            draft_length=len(draft["draft"]),
        )
        return draft

    except json.JSONDecodeError as e:
        logger.error("draft_writer_json_parse_error", error=str(e))
        return {
            "draft": "Failed to generate draft reply.",
            "tone": tone.value,
            "suggested_subject": f"Re: {email_data.get('subject', '')}",
        }
    except Exception as e:
        logger.error("draft_writer_error", error=str(e))
        return {
            "draft": f"Draft generation error: {str(e)[:100]}",
            "tone": tone.value,
            "suggested_subject": f"Re: {email_data.get('subject', '')}",
        }
