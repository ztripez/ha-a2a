"""Bridge from A2A messages to Home Assistant conversation APIs."""

from __future__ import annotations

from homeassistant.components import conversation
from homeassistant.core import Context, HomeAssistant


def _extract_speech_text(response_payload: dict) -> str:
    """Extract speech text from a conversation response payload."""
    response_obj = response_payload.get("response", {})
    speech_obj = response_obj.get("speech", {})
    plain = speech_obj.get("plain", {})
    if isinstance(plain, dict):
        text = plain.get("speech")
        if isinstance(text, str) and text:
            return text

    return "Assistant completed the request."


async def async_run_assistant_text(
    hass: HomeAssistant,
    *,
    assistant_id: str,
    text: str,
    user_context: Context,
    context_id: str,
) -> str:
    """Run one text turn through Home Assistant conversation."""
    result = await conversation.async_converse(
        hass=hass,
        text=text,
        conversation_id=context_id,
        context=user_context,
        agent_id=assistant_id,
    )
    return _extract_speech_text(result.as_dict())
