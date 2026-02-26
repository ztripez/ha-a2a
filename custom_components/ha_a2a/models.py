"""A2A boundary models and serialization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from a2a._base import A2ABaseModel
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    JSONRPCErrorResponse,
    JSONRPCSuccessResponse,
    Task,
    TaskState,
    TransportProtocol,
)

from .const import (
    AGENT_CARD_PATH_TEMPLATE,
    AGENT_CARD_VERSION,
    AGENT_INTERFACE_PATH_TEMPLATE,
    SUPPORTED_A2A_VERSION,
)


@dataclass(frozen=True, slots=True)
class A2AAssistantAgent:
    """Canonical internal representation of one assistant-facing A2A agent."""

    assistant_id: str
    name: str
    supports_streaming: bool


def build_agent_card_path(assistant_id: str) -> str:
    """Build an assistant-specific card path with proper escaping."""
    return AGENT_CARD_PATH_TEMPLATE.format(assistant_id=quote(assistant_id, safe=""))


def build_agent_interface_path(assistant_id: str) -> str:
    """Build an assistant-specific interface path with proper escaping."""
    return AGENT_INTERFACE_PATH_TEMPLATE.format(
        assistant_id=quote(assistant_id, safe="")
    )


def build_agent_card(
    agent: A2AAssistantAgent,
    *,
    base_url: str,
) -> AgentCard:
    """Create an A2A AgentCard model for a Home Assistant assistant."""
    interface_path = build_agent_interface_path(agent.assistant_id)
    interface_url = f"{base_url}{interface_path}"
    return AgentCard(
        name=agent.name,
        description=(
            f"A2A wrapper for Home Assistant assistant '{agent.name}' "
            "with assistant-scoped identity and task lifecycle."
        ),
        version=AGENT_CARD_VERSION,
        url=interface_url,
        protocol_version=SUPPORTED_A2A_VERSION,
        preferred_transport=TransportProtocol.jsonrpc.value,
        additional_interfaces=[
            AgentInterface(
                url=interface_url,
                transport=TransportProtocol.jsonrpc.value,
            )
        ],
        capabilities=AgentCapabilities(
            streaming=agent.supports_streaming,
            push_notifications=False,
            state_transition_history=True,
        ),
        security_schemes={},
        security=[],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id=agent.assistant_id,
                name=f"{agent.name} conversation",
                description="Conversational task execution via Home Assistant.",
                tags=["assistant", "conversation", "home-assistant"],
                examples=[
                    "Turn off the hallway lights.",
                    "Set the thermostat to 70 degrees.",
                ],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
    )


def dump_agent_card(agent_card: AgentCard) -> dict:
    """Serialize an AgentCard model to JSON-ready dict."""
    return agent_card.model_dump(mode="json", by_alias=True, exclude_none=True)


class ListTasksParams(A2ABaseModel):
    """Typed params for local `tasks/list` extension."""

    context_id: str | None = None
    status: TaskState | None = None
    page_size: int = 50
    page_token: str = "0"
    history_length: int | None = None
    include_artifacts: bool = False


class ListTasksRequest(A2ABaseModel):
    """JSON-RPC request model for local `tasks/list` extension."""

    id: str | int
    jsonrpc: Literal["2.0"] = "2.0"
    method: Literal["tasks/list"] = "tasks/list"
    params: ListTasksParams


class ListTasksResult(A2ABaseModel):
    """Result payload for local `tasks/list` extension."""

    tasks: list[Task]
    next_page_token: str
    page_size: int
    total_size: int


class ListTasksSuccessResponse(JSONRPCSuccessResponse):
    """JSON-RPC success response for local `tasks/list` extension."""

    result: ListTasksResult


class ListTasksResponse(A2ABaseModel):
    """JSON-RPC response union for local `tasks/list` extension."""

    root: ListTasksSuccessResponse | JSONRPCErrorResponse


def parse_task_state(value: str | None) -> TaskState | None:
    """Parse task state values from either enum form."""
    if value is None:
        return None

    normalized = value.strip()
    if normalized.startswith("TASK_STATE_"):
        normalized = normalized.removeprefix("TASK_STATE_").lower().replace("_", "-")

    return TaskState(normalized)
