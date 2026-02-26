# ha-a2a Agent Instructions

Home Assistant custom integration that exposes Home Assistant Assistants as A2A-compatible remote agents.

## Core Product Decision
- ALWAYS model the system as **one A2A agent per Home Assistant Assistant**.
- NEVER collapse all assistants into one aggregate A2A agent by default.
- PREFER stable per-assistant identity (agent card name/id/version) so clients can cache and route correctly.

## Mission
- Build a Home Assistant custom component that speaks A2A at the protocol boundary.
- Preserve strict A2A semantics while using Home Assistant-native async patterns.
- Start with a minimal, correct MVP and expand optional protocol features incrementally.

## Canonical Sources
- A2A specification: `https://a2a-protocol.org/latest/specification/`
- A2A normative proto: `https://github.com/a2aproject/A2A/blob/main/specification/a2a.proto`
- A2A Python SDK: `https://github.com/a2aproject/a2a-python`
- Home Assistant developer docs: `https://developers.home-assistant.io/`

## Project Scope
- Expose each Home Assistant Assistant through a dedicated A2A-facing interface.
- Implement agent discovery and core task/message lifecycle operations first.
- Map A2A messages, parts, and artifacts to Home Assistant conversation behavior.

## Non-Goals (Initial)
- Do not implement all optional A2A features before MVP correctness.
- Do not add speculative compatibility shims without active consumer evidence.
- Do not expose unauthenticated public endpoints by default.

## Suggested Layout
- `custom_components/ha_a2a/manifest.json` - integration metadata
- `custom_components/ha_a2a/__init__.py` - setup/unload and registrations
- `custom_components/ha_a2a/const.py` - constants and config keys
- `custom_components/ha_a2a/config_flow.py` - config entry and options flow
- `custom_components/ha_a2a/models.py` - boundary models and schema mappings
- `custom_components/ha_a2a/store.py` - task/context persistence and lookup
- `custom_components/ha_a2a/assistant_registry.py` - assistant-to-agent mapping
- `custom_components/ha_a2a/conversation_bridge.py` - bridge into HA conversation APIs
- `custom_components/ha_a2a/http.py` - HTTP/JSON A2A endpoints
- `custom_components/ha_a2a/ws_api.py` - optional websocket support
- `tests/components/ha_a2a/` - integration and protocol tests

## Protocol Rules (A2A)
- ALWAYS treat `a2a.proto` as the normative contract.
- ALWAYS serve accurate Agent Card metadata for each assistant-facing agent.
- ALWAYS declare capability flags truthfully (`streaming`, `pushNotifications`, `extendedAgentCard`).
- ALWAYS return protocol-appropriate errors for unsupported optional operations.
- ALWAYS validate requested `A2A-Version` and fail explicitly when unsupported.
- ALWAYS preserve task/event ordering guarantees in stream responses.

## Assistant Mapping Rules
- Each Home Assistant Assistant MUST map to one logical A2A agent identity.
- Each mapped agent SHOULD publish assistant-specific skills/examples in its Agent Card.
- A2A task and context IDs MUST remain stable and independent from internal HA implementation details.
- Assistant selection MUST be deterministic and auditable from request metadata.

## Home Assistant Integration Rules
- ALWAYS use async-first patterns and never block the event loop.
- ALWAYS register HTTP views in `async_setup` and cleanly unregister on unload.
- ALWAYS store runtime objects in `entry.runtime_data`.
- ALWAYS preserve HA auth/user context in request handling and task visibility.
- PREFER in-process conversation APIs for assistant calls when available.

## Data Model and Validation Rules
- ALWAYS validate inbound and outbound protocol payloads.
- ALWAYS use canonical internal types for task/message/artifact concepts.
- NEVER duplicate parallel data models for the same concept without hard need.
- NEVER hand-roll ad-hoc dict transformations when typed models are available.

## Error Handling Rules
- ALWAYS fail loudly on invalid state, schema mismatch, or unsupported operation.
- NEVER swallow exceptions silently.
- NEVER defer required behavior with TODO placeholders in runtime code paths.
- ALWAYS include task/context identifiers in logs for traceability.

## Security Rules
- ALWAYS require Home Assistant authentication unless endpoint is intentionally public.
- ALWAYS scope task access to the authenticated principal.
- NEVER leak resource existence across unauthorized users.
- PREFER local-only or explicitly trusted deployment surfaces during early iterations.

## MVP Implementation Order
1. Per-assistant Agent Card endpoint(s)
2. `SendMessage` (non-streaming) with task creation/update behavior
3. `GetTask`
4. `ListTasks`
5. `CancelTask`
6. Streaming (`SendStreamingMessage`, `SubscribeToTask`)
7. Push notification configuration operations
8. Extended agent card

## Testing Requirements
- ALWAYS add tests for every implemented protocol operation.
- ALWAYS test both success and failure paths (auth, validation, not found, unsupported).
- ALWAYS test capability gating behavior against declared Agent Card capabilities.
- ALWAYS test task lifecycle state transitions.
- ALWAYS test stream ordering, disconnect handling, and cancellation behavior.

## Quality Gates
- Run lint, type checks, and tests before closing implementation work.
- PREFER focused component tests plus at least one end-to-end A2A flow test.

## Workflow
- Use `bd` for strategic multi-step work and discovered follow-ups.
- Record newly discovered follow-up tasks rather than leaving ad-hoc notes.
- On session close, run: `bd sync --flush-only`.
