"""A2A SDK runtime wiring for Home Assistant assistants."""

from __future__ import annotations

from dataclasses import dataclass

from a2a.auth.user import User
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.context import ServerCallContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler, JSONRPCHandler
from a2a.server.tasks import TaskUpdater
from a2a.types import Part, TextPart
from homeassistant.core import Context, HomeAssistant

from .conversation_bridge import async_run_assistant_text
from .models import A2AAssistantAgent, build_agent_card
from .store import HaScopedTaskStore


class HAUser(User):
    """A2A SDK user adapter backed by Home Assistant auth context."""

    def __init__(self, user_id: str | None) -> None:
        """Store Home Assistant user identity."""
        self._user_id = user_id

    @property
    def is_authenticated(self) -> bool:
        """Return whether the request is authenticated."""
        return self._user_id is not None

    @property
    def user_name(self) -> str:
        """Return stable principal identifier for SDK context."""
        return self._user_id or ""


def build_server_call_context(
    ha_context: Context,
    *,
    request: object,
) -> ServerCallContext:
    """Create SDK call context from Home Assistant request context."""
    return ServerCallContext(
        user=HAUser(ha_context.user_id),
        state={
            "ha_user_id": ha_context.user_id,
            "ha_context": ha_context,
            "ha_request": request,
        },
    )


class HaConversationAgentExecutor(AgentExecutor):
    """AgentExecutor that proxies execution into HA conversation APIs."""

    def __init__(self, hass: HomeAssistant, assistant_id: str) -> None:
        """Initialize executor for one assistant ID."""
        self._hass = hass
        self._assistant_id = assistant_id

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute one agent request and publish SDK events."""
        task_id = context.task_id
        context_id = context.context_id
        if task_id is None or context_id is None:
            raise ValueError("task_id and context_id are required")

        if context.call_context is None:
            raise ValueError("call context is required")

        ha_context = context.call_context.state.get("ha_context")
        if not isinstance(ha_context, Context):
            raise ValueError("missing Home Assistant request context")

        updater = TaskUpdater(event_queue, task_id=task_id, context_id=context_id)
        await updater.start_work()

        user_text = context.get_user_input()
        try:
            assistant_text = await async_run_assistant_text(
                self._hass,
                assistant_id=self._assistant_id,
                text=user_text,
                user_context=ha_context,
                context_id=context_id,
            )
        except Exception as err:
            failed_message = updater.new_agent_message(
                parts=[Part(root=TextPart(text=f"Assistant execution failed: {err}"))]
            )
            await updater.failed(failed_message)
            return

        parts = [Part(root=TextPart(text=assistant_text))]
        await updater.add_artifact(
            parts=parts,
            name="assistant_response",
            metadata={},
        )
        completed_message = updater.new_agent_message(parts=parts)
        await updater.complete(completed_message)

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Publish cancellation state for the requested task."""
        task_id = context.task_id
        context_id = context.context_id
        if task_id is None or context_id is None:
            raise ValueError("task_id and context_id are required")

        updater = TaskUpdater(event_queue, task_id=task_id, context_id=context_id)
        canceled_message = updater.new_agent_message(
            parts=[Part(root=TextPart(text="Task was canceled"))]
        )
        await updater.cancel(canceled_message)


@dataclass(slots=True)
class AssistantRuntime:
    """Per-assistant SDK runtime wiring."""

    task_store: HaScopedTaskStore
    request_handler: DefaultRequestHandler


def build_assistant_runtime(hass: HomeAssistant, assistant_id: str) -> AssistantRuntime:
    """Create per-assistant runtime service objects."""
    task_store = HaScopedTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=HaConversationAgentExecutor(hass, assistant_id),
        task_store=task_store,
    )
    return AssistantRuntime(task_store=task_store, request_handler=request_handler)


def build_jsonrpc_handler(
    runtime: AssistantRuntime,
    assistant: A2AAssistantAgent,
    *,
    base_url: str,
) -> JSONRPCHandler:
    """Create JSONRPC handler bound to assistant AgentCard."""
    agent_card = build_agent_card(assistant, base_url=base_url)
    return JSONRPCHandler(
        agent_card=agent_card, request_handler=runtime.request_handler
    )
