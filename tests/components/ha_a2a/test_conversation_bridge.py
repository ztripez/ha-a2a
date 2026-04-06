"""Tests for conversation_bridge.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from .conftest import _ensure_ha_stubs, _load_module

_ensure_ha_stubs()
bridge = _load_module("conversation_bridge", "conversation_bridge.py")

_FALLBACK = "Assistant completed the request."


class TestExtractSpeechText:
    """Test _extract_speech_text helper."""

    def test_extracts_valid_speech(self) -> None:
        payload = {
            "response": {
                "speech": {
                    "plain": {"speech": "The lights are off."},
                },
            },
        }
        assert bridge._extract_speech_text(payload) == "The lights are off."

    def test_fallback_when_speech_missing(self) -> None:
        payload = {"response": {}}
        assert bridge._extract_speech_text(payload) == _FALLBACK

    def test_fallback_when_speech_empty(self) -> None:
        payload = {
            "response": {
                "speech": {
                    "plain": {"speech": ""},
                },
            },
        }
        assert bridge._extract_speech_text(payload) == _FALLBACK

    def test_fallback_when_plain_not_dict(self) -> None:
        payload = {
            "response": {
                "speech": {
                    "plain": "unexpected string",
                },
            },
        }
        assert bridge._extract_speech_text(payload) == _FALLBACK

    def test_fallback_when_payload_empty(self) -> None:
        assert bridge._extract_speech_text({}) == _FALLBACK

    def test_fallback_when_speech_is_none(self) -> None:
        payload = {
            "response": {
                "speech": {
                    "plain": {"speech": None},
                },
            },
        }
        assert bridge._extract_speech_text(payload) == _FALLBACK


class TestAsyncRunAssistantText:
    """Test async_run_assistant_text."""

    async def test_success_returns_speech(self) -> None:
        """Happy path: conversation returns valid speech text."""
        import sys

        ha_conv = sys.modules["homeassistant.components.conversation"]

        mock_result = MagicMock()
        mock_result.as_dict.return_value = {
            "response": {
                "speech": {"plain": {"speech": "Done! Lights off."}},
            },
        }
        ha_conv.async_converse = AsyncMock(return_value=mock_result)

        # Reload to pick up patched async_converse
        bridge_mod = _load_module("conversation_bridge", "conversation_bridge.py")

        ha_core = sys.modules["homeassistant.core"]
        ctx = ha_core.Context()
        ctx.user_id = "test-user"
        hass = MagicMock()

        result = await bridge_mod.async_run_assistant_text(
            hass,
            assistant_id="assist-1",
            text="Turn off lights",
            user_context=ctx,
            context_id="ctx-1",
        )

        assert result == "Done! Lights off."
        ha_conv.async_converse.assert_awaited_once_with(
            hass=hass,
            text="Turn off lights",
            conversation_id="ctx-1",
            context=ctx,
            agent_id="assist-1",
        )

    async def test_exception_propagates(self) -> None:
        """Exceptions from async_converse should propagate to caller."""
        import sys

        ha_conv = sys.modules["homeassistant.components.conversation"]
        ha_conv.async_converse = AsyncMock(side_effect=RuntimeError("HA down"))

        bridge_mod = _load_module("conversation_bridge", "conversation_bridge.py")

        ha_core = sys.modules["homeassistant.core"]
        ctx = ha_core.Context()
        ctx.user_id = "test-user"
        hass = MagicMock()

        with pytest.raises(RuntimeError, match="HA down"):
            await bridge_mod.async_run_assistant_text(
                hass,
                assistant_id="assist-1",
                text="Hello",
                user_context=ctx,
                context_id="ctx-1",
            )
