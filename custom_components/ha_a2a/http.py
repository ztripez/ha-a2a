"""HTTP endpoints for A2A discovery and JSON-RPC transport."""

from __future__ import annotations

from typing import cast

from aiohttp import web

from a2a.server.request_handlers import JSONRPCHandler
from a2a.types import (
    CancelTaskRequest,
    DeleteTaskPushNotificationConfigRequest,
    GetTaskPushNotificationConfigRequest,
    GetTaskRequest,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    JSONParseError,
    JSONRPCError,
    JSONRPCErrorResponse,
    ListTaskPushNotificationConfigRequest,
    MethodNotFoundError,
    SendMessageRequest,
    SendStreamingMessageRequest,
    SetTaskPushNotificationConfigRequest,
    TaskResubscriptionRequest,
)
from homeassistant.components import http as ha_http
from homeassistant.core import Context

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
        payload = {
            "agents": [
                {
                    "assistant_id": agent.assistant_id,
                    "card_url": f"{base_url}{build_agent_card_path(agent.assistant_id)}",
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
    """JSON-RPC endpoint for per-assistant A2A operations."""

    url = AGENT_RPC_PATH
    name = "api:ha_a2a:agent_rpc"
    requires_auth = True

    async def post(
        self, request: web.Request, assistant_id: str
    ) -> web.StreamResponse | web.Response:
        """Handle JSON-RPC method dispatch."""
        hass = request.app[ha_http.KEY_HASS]
        registry = _get_registry(hass)
        runtimes = _get_runtime_cache(hass)

        assistant = await registry.async_get_agent(assistant_id)
        if assistant is None:
            raise web.HTTPNotFound(text=f"Unknown assistant ID: {assistant_id}")

        if _validate_a2a_version(request) is False:
            error_payload = JSONRPCErrorResponse(
                id=None,
                error=JSONRPCError(
                    code=-32013,
                    message="Requested A2A-Version is not supported",
                    data={
                        "error": "VersionNotSupportedError",
                        "supported": SUPPORTED_A2A_VERSION,
                    },
                ),
            )
            return self.json(
                error_payload.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        try:
            body = await request.json()
        except ValueError as err:
            parse_error = JSONRPCErrorResponse(
                id=None,
                error=JSONParseError(message=str(err)),
            )
            return self.json(
                parse_error.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        request_id = body.get("id") if isinstance(body, dict) else None
        if not isinstance(body, dict):
            invalid_request = JSONRPCErrorResponse(
                id=request_id,
                error=InvalidRequestError(message="JSON-RPC request must be an object"),
            )
            return self.json(
                invalid_request.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            )

        if body.get("jsonrpc") != "2.0":
            invalid_jsonrpc = JSONRPCErrorResponse(
                id=request_id,
                error=InvalidRequestError(message="jsonrpc must be '2.0'"),
            )
            return self.json(
                invalid_jsonrpc.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            )

        runtime = _get_or_create_runtime(runtimes, hass, assistant_id)
        handler = build_jsonrpc_handler(
            runtime,
            assistant,
            base_url=f"{request.scheme}://{request.host}",
        )
        call_context = build_server_call_context(self.context(request), request=request)

        method = body.get("method")
        if not isinstance(method, str):
            invalid_method = JSONRPCErrorResponse(
                id=request_id,
                error=InvalidRequestError(message="method must be a string"),
            )
            return self.json(
                invalid_method.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method in {"message/stream", "tasks/resubscribe"}:
            return await _handle_streaming_method(handler, method, body, call_context)

        return await _handle_unary_method(handler, runtime, method, body, call_context)


def _get_registry(hass) -> AssistantRegistry:
    """Get configured assistant registry service."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or DATA_REGISTRY not in domain_data:
        raise web.HTTPInternalServerError(text="ha_a2a runtime is not initialized")

    return cast(AssistantRegistry, domain_data[DATA_REGISTRY])


def _get_runtime_cache(hass) -> dict[str, AssistantRuntime]:
    """Get per-assistant runtime cache."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or DATA_STORE not in domain_data:
        raise web.HTTPInternalServerError(text="ha_a2a runtime is not initialized")

    return cast(dict[str, AssistantRuntime], domain_data[DATA_STORE])


def _get_or_create_runtime(
    runtimes: dict[str, AssistantRuntime],
    hass,
    assistant_id: str,
) -> AssistantRuntime:
    """Return existing runtime or create one for assistant ID."""
    runtime = runtimes.get(assistant_id)
    if runtime is None:
        runtime = build_assistant_runtime(hass, assistant_id)
        runtimes[assistant_id] = runtime
    return runtime


async def _handle_unary_method(
    handler: JSONRPCHandler,
    runtime: AssistantRuntime,
    method: str,
    body: dict,
    call_context,
) -> web.Response:
    """Handle non-streaming JSON-RPC methods with SDK models."""
    try:
        if method == "message/send":
            req = SendMessageRequest.model_validate(body)
            resp = await handler.on_message_send(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/get":
            req = GetTaskRequest.model_validate(body)
            resp = await handler.on_get_task(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/cancel":
            req = CancelTaskRequest.model_validate(body)
            resp = await handler.on_cancel_task(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/pushNotificationConfig/set":
            req = SetTaskPushNotificationConfigRequest.model_validate(body)
            resp = await handler.set_push_notification_config(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/pushNotificationConfig/get":
            req = GetTaskPushNotificationConfigRequest.model_validate(body)
            resp = await handler.get_push_notification_config(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/pushNotificationConfig/list":
            req = ListTaskPushNotificationConfigRequest.model_validate(body)
            resp = await handler.list_push_notification_config(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/pushNotificationConfig/delete":
            req = DeleteTaskPushNotificationConfigRequest.model_validate(body)
            resp = await handler.delete_push_notification_config(req, call_context)
            return web.json_response(
                resp.root.model_dump(mode="json", by_alias=True, exclude_none=True)
            )

        if method == "tasks/list":
            return _handle_tasks_list_extension(runtime, body, call_context)

        not_found = JSONRPCErrorResponse(
            id=body.get("id"),
            error=MethodNotFoundError(message=f"Method not supported: {method}"),
        )
        return web.json_response(
            not_found.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
    except ValueError as err:
        invalid_state = JSONRPCErrorResponse(
            id=body.get("id"),
            error=InvalidParamsError(message=str(err)),
        )
        return web.json_response(
            invalid_state.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
    except Exception as err:  # pragma: no cover - safety fallback
        internal = JSONRPCErrorResponse(
            id=body.get("id"),
            error=InternalError(message=str(err)),
        )
        return web.json_response(
            internal.model_dump(mode="json", by_alias=True, exclude_none=True)
        )


async def _handle_streaming_method(
    handler: JSONRPCHandler,
    method: str,
    body: dict,
    call_context,
) -> web.StreamResponse:
    """Handle streaming methods and return SSE responses."""
    stream_response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    await stream_response.prepare(
        cast(web.BaseRequest, call_context.state.get("ha_request"))
    )

    try:
        if method == "message/stream":
            req = SendStreamingMessageRequest.model_validate(body)
            stream = handler.on_message_send_stream(req, call_context)
        else:
            req = TaskResubscriptionRequest.model_validate(body)
            stream = handler.on_resubscribe_to_task(req, call_context)

        async for item in stream:
            payload = item.root.model_dump_json(by_alias=True, exclude_none=True)
            await stream_response.write(f"data: {payload}\n\n".encode())
    except Exception as err:
        error_response = JSONRPCErrorResponse(
            id=body.get("id"),
            error=InternalError(message=str(err)),
        )
        payload = error_response.model_dump_json(by_alias=True, exclude_none=True)
        await stream_response.write(f"data: {payload}\n\n".encode())

    await stream_response.write_eof()
    return stream_response


def _handle_tasks_list_extension(
    runtime: AssistantRuntime,
    body: dict,
    call_context,
) -> web.Response:
    """Handle local typed `tasks/list` extension."""
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
