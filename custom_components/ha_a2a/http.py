"""HTTP endpoints for A2A discovery and JSON-RPC transport.

Uses the SDK's JSONRPCHandler for all standard method dispatch, validation,
capability gating, and error formatting. Only the aiohttp transport layer and
the local ``tasks/list`` extension are handled here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from a2a.server.request_handlers import JSONRPCHandler
from a2a.types import (
    A2ARequest,
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetAuthenticatedExtendedCardRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    JSONParseError,
    JSONRPCError,
    JSONRPCErrorResponse,
    JSONRPCRequest,
    ListTaskPushNotificationConfigRequest,
    MethodNotFoundError,
    SendMessageRequest,
    SendStreamingMessageRequest,
    SetTaskPushNotificationConfigRequest,
    TaskResubscriptionRequest,
    UnsupportedOperationError,
)
from a2a.utils.errors import ServerError
from aiohttp import web
from homeassistant.components import http as ha_http
from pydantic import ValidationError

from .assistant_registry import AssistantRegistry
from .const import (
    AGENT_RPC_PATH,
    DATA_REGISTRY,
    DATA_STORE,
    DOMAIN,
    LIST_AGENT_CARDS_PATH,
    SUPPORTED_A2A_VERSION,
)
from .models import (
    ListTasksRequest,
    ListTasksResult,
    ListTasksSuccessResponse,
    build_agent_card,
    build_agent_card_path,
    dump_agent_card,
    parse_task_state,
)
from .sdk_runtime import (
    AssistantRuntime,
    build_assistant_runtime,
    build_jsonrpc_handler,
    build_server_call_context,
)

logger = logging.getLogger(__name__)

# SDK method→model map for standard A2A methods.
_METHOD_TO_MODEL: dict[str, type] = {
    model.model_fields["method"].default: model
    for model in A2ARequest.model_fields["root"].annotation.__args__
}

# Streaming request types that require SSE responses.
_STREAMING_TYPES = (SendStreamingMessageRequest, TaskResubscriptionRequest)


class A2AAgentCardsView(ha_http.HomeAssistantView):
    """List per-assistant A2A Agent Cards."""

    url = LIST_AGENT_CARDS_PATH
    name = "api:ha_a2a:agent_cards"
    requires_auth = True

    async def get(self, request: web.Request) -> web.Response:
        """Handle list card requests."""
        hass = request.app[ha_http.KEY_HASS]
        registry = _get_registry(hass)
        base_url = f"{request.scheme}://{request.host}"

        agents = await registry.async_list_agents()
        _evict_stale_runtimes(_get_runtime_cache(hass), agents)
        payload = {
            "agents": [
                {
                    "assistant_id": agent.assistant_id,
                    "card_url": (
                        f"{base_url}{build_agent_card_path(agent.assistant_id)}"
                    ),
                    "card": dump_agent_card(build_agent_card(agent, base_url=base_url)),
                }
                for agent in agents
            ]
        }
        return self.json(payload)


class A2AAgentCardView(ha_http.HomeAssistantView):
    """Return one assistant-specific A2A Agent Card."""

    url = "/api/ha_a2a/agents/{assistant_id}/.well-known/agent-card.json"
    name = "api:ha_a2a:agent_card"
    requires_auth = True

    async def get(self, request: web.Request, assistant_id: str) -> web.Response:
        """Handle single card requests."""
        hass = request.app[ha_http.KEY_HASS]
        registry = _get_registry(hass)
        agent = await registry.async_get_agent(assistant_id)
        if agent is None:
            raise web.HTTPNotFound(text=f"Unknown assistant ID: {assistant_id}")

        base_url = f"{request.scheme}://{request.host}"
        return self.json(dump_agent_card(build_agent_card(agent, base_url=base_url)))


class A2AAgentRpcView(ha_http.HomeAssistantView):
    """JSON-RPC endpoint for per-assistant A2A operations.

    Delegates standard A2A methods to the SDK's JSONRPCHandler and handles
    the local ``tasks/list`` extension directly.
    """

    url = AGENT_RPC_PATH
    name = "api:ha_a2a:agent_rpc"
    requires_auth = True

    async def post(
        self, request: web.Request, assistant_id: str
    ) -> web.StreamResponse | web.Response:
        """Route JSON-RPC requests through the SDK handler."""
        hass = request.app[ha_http.KEY_HASS]
        registry = _get_registry(hass)
        runtimes = _get_runtime_cache(hass)

        assistant = await registry.async_get_agent(assistant_id)
        if assistant is None:
            raise web.HTTPNotFound(text=f"Unknown assistant ID: {assistant_id}")

        # --- A2A version gate ---
        if not _validate_a2a_version(request):
            return _json_rpc_error_response(
                request_id=None,
                error=JSONRPCError(
                    code=-32013,
                    message="Requested A2A-Version is not supported",
                    data={
                        "error": "VersionNotSupportedError",
                        "supported": SUPPORTED_A2A_VERSION,
                    },
                ),
            )

        # --- Parse body ---
        try:
            body = await request.json()
        except ValueError as err:
            return _json_rpc_error_response(
                request_id=None,
                error=JSONParseError(message=str(err)),
            )

        request_id = body.get("id") if isinstance(body, dict) else None

        # --- Validate base JSON-RPC structure ---
        try:
            base_request = JSONRPCRequest.model_validate(body)
        except ValidationError as exc:
            return _json_rpc_error_response(
                request_id=request_id,
                error=InvalidRequestError(data=json.loads(exc.json())),
            )

        method = base_request.method

        # --- Local extension: tasks/list (not yet in SDK) ---
        if method == "tasks/list":
            runtime = _get_or_create_runtime(runtimes, hass, assistant_id)
            call_context = build_server_call_context(
                self.context(request), request=request
            )
            return _handle_tasks_list(runtime, body, call_context)

        # --- Route to SDK handler ---
        model_class = _METHOD_TO_MODEL.get(method)
        if model_class is None:
            return _json_rpc_error_response(
                request_id=request_id,
                error=MethodNotFoundError(),
            )

        try:
            specific_request = model_class.model_validate(body)
        except ValidationError as exc:
            return _json_rpc_error_response(
                request_id=request_id,
                error=InvalidParamsError(data=json.loads(exc.json())),
            )

        runtime = _get_or_create_runtime(runtimes, hass, assistant_id)
        handler = build_jsonrpc_handler(
            runtime,
            assistant,
            base_url=f"{request.scheme}://{request.host}",
        )
        call_context = build_server_call_context(self.context(request), request=request)

        if isinstance(specific_request, _STREAMING_TYPES):
            return await _handle_streaming(
                handler, specific_request, call_context, request
            )

        return await _handle_unary(handler, specific_request, call_context)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_registry(hass: Any) -> AssistantRegistry:
    """Get configured assistant registry service."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or DATA_REGISTRY not in domain_data:
        raise web.HTTPInternalServerError(text="ha_a2a runtime is not initialized")
    return cast(AssistantRegistry, domain_data[DATA_REGISTRY])


def _get_runtime_cache(hass: Any) -> dict[str, AssistantRuntime]:
    """Get per-assistant runtime cache."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or DATA_STORE not in domain_data:
        raise web.HTTPInternalServerError(text="ha_a2a runtime is not initialized")
    return cast(dict[str, AssistantRuntime], domain_data[DATA_STORE])


def _evict_stale_runtimes(
    runtimes: dict[str, AssistantRuntime],
    current_agents: list[Any],
) -> None:
    """Remove cached runtimes for assistants no longer in the registry."""
    active_ids = {agent.assistant_id for agent in current_agents}
    stale_ids = [rid for rid in runtimes if rid not in active_ids]
    for rid in stale_ids:
        del runtimes[rid]
        logger.info("Evicted stale runtime for assistant %s", rid)


def _get_or_create_runtime(
    runtimes: dict[str, AssistantRuntime],
    hass: Any,
    assistant_id: str,
) -> AssistantRuntime:
    """Return existing runtime or create one for assistant ID."""
    runtime = runtimes.get(assistant_id)
    if runtime is None:
        runtime = build_assistant_runtime(hass, assistant_id)
        runtimes[assistant_id] = runtime
    return runtime


def _json_rpc_error_response(
    *,
    request_id: str | int | None,
    error: JSONRPCError,
) -> web.Response:
    """Build a JSON-RPC error response as an aiohttp Response."""
    payload = JSONRPCErrorResponse(id=request_id, error=error)
    return web.json_response(
        payload.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


async def _handle_unary(
    handler: JSONRPCHandler,
    request_obj: Any,
    call_context: Any,
) -> web.Response:
    """Dispatch a non-streaming request through the SDK handler.

    SDK capability-gating decorators (``@validate``) raise ``ServerError``
    before the handler body runs, so we catch it here and format the
    protocol-appropriate error response.
    """
    try:
        result = await _dispatch_unary(handler, request_obj, call_context)
    except ServerError as exc:
        error = exc.error if exc.error else InternalError()
        return _json_rpc_error_response(
            request_id=getattr(request_obj, "id", None),
            error=error,
        )

    if isinstance(result, JSONRPCErrorResponse):
        return web.json_response(
            result.model_dump(mode="json", by_alias=True, exclude_none=True)
        )

    return web.json_response(
        result.root.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


async def _dispatch_unary(
    handler: JSONRPCHandler,
    request_obj: Any,
    call_context: Any,
) -> Any:
    """Route a validated request to the matching SDK handler method."""
    match request_obj:
        case SendMessageRequest():
            return await handler.on_message_send(request_obj, call_context)
        case CancelTaskRequest():
            return await handler.on_cancel_task(request_obj, call_context)
        case GetTaskRequest():
            return await handler.on_get_task(request_obj, call_context)
        case SetTaskPushNotificationConfigRequest():
            return await handler.set_push_notification_config(request_obj, call_context)
        case GetTaskPushNotificationConfigRequest():
            return await handler.get_push_notification_config(request_obj, call_context)
        case ListTaskPushNotificationConfigRequest():
            return await handler.list_push_notification_config(
                request_obj, call_context
            )
        case DeleteTaskPushNotificationConfigRequest():
            return await handler.delete_push_notification_config(
                request_obj, call_context
            )
        case GetAuthenticatedExtendedCardRequest():
            return await handler.get_authenticated_extended_card(
                request_obj, call_context
            )
        case _:
            error = UnsupportedOperationError(
                message=f"Request type {type(request_obj).__name__} is unknown."
            )
            return JSONRPCErrorResponse(id=request_obj.id, error=error)


async def _handle_streaming(
    handler: JSONRPCHandler,
    request_obj: SendStreamingMessageRequest | TaskResubscriptionRequest,
    call_context: Any,
    ha_request: web.Request,
) -> web.StreamResponse | web.Response:
    """Dispatch a streaming request and return an SSE response.

    SDK capability-gating decorators may raise ``ServerError`` before any
    events are yielded (e.g. streaming disabled). In that case we return
    a plain JSON error response instead of opening an SSE stream.
    """
    try:
        if isinstance(request_obj, SendStreamingMessageRequest):
            stream = handler.on_message_send_stream(request_obj, call_context)
        else:
            stream = handler.on_resubscribe_to_task(request_obj, call_context)
    except ServerError as exc:
        error = exc.error if exc.error else InternalError()
        return _json_rpc_error_response(
            request_id=getattr(request_obj, "id", None),
            error=error,
        )

    stream_response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await stream_response.prepare(ha_request)

    try:
        async for item in stream:
            payload = item.root.model_dump_json(by_alias=True, exclude_none=True)
            await stream_response.write(f"data: {payload}\n\n".encode())
    except Exception as err:
        logger.exception("Streaming error for %s", type(request_obj).__name__)
        error_resp = JSONRPCErrorResponse(
            id=request_obj.id,
            error=InternalError(message=str(err)),
        )
        payload = error_resp.model_dump_json(by_alias=True, exclude_none=True)
        await stream_response.write(f"data: {payload}\n\n".encode())

    await stream_response.write_eof()
    return stream_response


def _handle_tasks_list(
    runtime: AssistantRuntime,
    body: dict,
    call_context: Any,
) -> web.Response:
    """Handle local typed ``tasks/list`` extension (not yet in SDK)."""
    req = ListTasksRequest.model_validate(body)
    params = req.params
    status = parse_task_state(
        params.status.value if params.status is not None else None
    )

    owner_user_id = cast(str | None, call_context.state.get("ha_user_id"))
    tasks, next_page_token, total_size = runtime.task_store.list_tasks(
        owner_user_id=owner_user_id,
        context_id=params.context_id,
        status=status,
        page_size=params.page_size,
        page_token=params.page_token,
    )

    rendered_tasks = []
    for task in tasks:
        rendered = task.model_copy(deep=True)
        if not params.include_artifacts:
            rendered = rendered.model_copy(update={"artifacts": None})
        if params.history_length is not None:
            if params.history_length <= 0:
                rendered = rendered.model_copy(update={"history": []})
            elif rendered.history is not None:
                rendered = rendered.model_copy(
                    update={"history": rendered.history[-params.history_length :]}
                )
        rendered_tasks.append(rendered)

    result = ListTasksResult(
        tasks=rendered_tasks,
        next_page_token=next_page_token,
        page_size=params.page_size,
        total_size=total_size,
    )
    response = ListTasksSuccessResponse(id=req.id, result=result)
    return web.json_response(
        response.model_dump(mode="json", by_alias=True, exclude_none=True)
    )


def _validate_a2a_version(request: web.Request) -> bool:
    """Validate A2A-Version header/query value."""
    requested = request.headers.get("A2A-Version")
    if requested is None:
        requested = request.query.get("A2A-Version", "")

    requested = requested.strip()
    if requested == "":
        requested = SUPPORTED_A2A_VERSION

    return requested == SUPPORTED_A2A_VERSION
