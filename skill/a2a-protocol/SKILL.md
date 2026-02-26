---
name: a2a-protocol
description: Implement A2A server protocol compliance and per-agent mappings when building `message/send`, `message/stream`, task lifecycle, agent cards, and capability-gated errors, or when reviewing A2A endpoint behavior; not for Home Assistant UI work, generic API performance tuning, or test-coverage-only audits.
---

# Purpose
Use this skill to keep A2A server behavior protocol-correct by treating `specification/a2a.proto` as the normative contract and mapping operations, objects, errors, capabilities, and versioning rules consistently.
You are enforcing wire-level correctness, not inventing protocol behavior.

# When to use this skill
- You are implementing or reviewing A2A endpoints like `message/send`, `message/stream`, `tasks/get`, `tasks/list`, or `tasks/cancel`.
- You are defining or validating Agent Card metadata and capability flags (`streaming`, `pushNotifications`, `extendedAgentCard`).
- You are mapping internal assistant behavior to A2A `Task`, `Message`, `Part`, and `Artifact` objects.
- You need to enforce protocol-specific error behavior, service parameters (`A2A-Version`, `A2A-Extensions`), or task-state transitions.
- You need to verify streaming ordering guarantees, push notification payload shape, or version negotiation behavior.

# When NOT to use this skill
- The task is primarily Home Assistant frontend, dashboards, or UI interaction design.
- The task is only test strategy depth and coverage quality (use `qa-coverage`).
- The task is compatibility-layer approval and deprecation governance without protocol implementation work (use `compatibility-gate`).
- The task is general code cleanup, DRY/KISS review, or architecture simplification without A2A contract work (use `code-hygiene`).

# Inputs
- Target code paths that implement A2A handlers, models, transport bindings, or agent-card generation.
- Declared scope (MVP vs full feature set) and required operations.
- Current/target A2A version(s) and expected client behavior.
- Capability matrix (`streaming`, `pushNotifications`, `extendedAgentCard`, extensions).
- Auth and tenancy expectations (who can see which tasks).
- Existing tests, fixtures, and sample payloads if available.
- Canonical references:
  - `https://a2a-protocol.org/latest/specification/`
  - `https://github.com/a2aproject/A2A/blob/main/specification/a2a.proto`

# Outputs
- A protocol-compliance implementation or review plan with explicit operation coverage.
- An operation matrix that marks each method as implemented, unsupported-with-correct-error, or out-of-scope.
- Concrete mapping for A2A objects and task lifecycle transitions.
- Capability-gating and error-mapping rules tied to declared Agent Card values.
- A version-handling decision with explicit fail behavior for unsupported versions.
- A checklist of required tests for success and failure paths.

# Workflow
1. Lock to normative protocol sources first:
   - Use `a2a.proto` for objects, enums, fields, and RPC names.
   - Use the spec doc for semantics (ordering, capability gates, authz behavior).
2. Build the operation matrix with concrete required vs optional methods:
   - Core: `SendMessage`, `SendStreamingMessage`, `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`.
   - Optional set: `Create/Get/List/DeleteTaskPushNotificationConfig`, `GetExtendedAgentCard`.
3. Verify Agent Card correctness:
   - Ensure `name`, `description`, `version`, `supportedInterfaces`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, and `skills` are coherent.
   - Ensure capability flags are truthful; do not advertise unimplemented features.
4. Map canonical data objects and fields exactly:
   - `Task`: `id`, `context_id`, `status`, `artifacts`, `history`, `metadata`.
   - `Message`: `message_id`, `role`, `parts`, optional `context_id`, `task_id`, `reference_task_ids`.
   - `Part`: oneof content (`text`, `raw`, `url`, `data`) plus `media_type`, optional metadata/filename.
   - `Artifact`: `artifact_id`, `parts`, optional descriptors.
5. Enforce lifecycle semantics and allowed transitions:
   - Respect `TASK_STATE_*` values including terminal (`COMPLETED`, `FAILED`, `CANCELED`, `REJECTED`) and interrupted (`INPUT_REQUIRED`, `AUTH_REQUIRED`).
   - Reject invalid continuation messages to terminal tasks with protocol errors.
6. Enforce streaming contract:
   - `message/stream` must either return one `Message` then close, or `Task` then ordered status/artifact updates until terminal close.
   - `SubscribeToTask` must emit current `Task` first, then ordered updates, then close at terminal state.
7. Enforce List/Get semantics that are easy to get wrong:
   - `history_length`: unset = server default, `0` = no history, positive = upper bound.
   - `ListTasks.next_page_token` must be present; use empty string when no next page.
   - If `include_artifacts` is false, omit artifacts from each task payload.
8. Enforce capability-gated behavior and explicit errors:
   - No streaming support -> `UnsupportedOperationError` for streaming methods.
   - No push support -> `PushNotificationNotSupportedError` for push config methods.
   - No extended card support -> `UnsupportedOperationError` for `GetExtendedAgentCard`.
   - Unsupported version -> `VersionNotSupportedError`.
9. Enforce service parameter handling:
   - Parse and validate `A2A-Version` and `A2A-Extensions`.
   - Match `Major.Minor` semantics, fail loudly when unsupported.
10. Enforce authz and tenancy constraints:
   - Authenticate requests.
   - Scope task access to principal/tenant.
   - Do not leak task existence to unauthorized callers.
11. Apply safety gates:
   - Require explicit user confirmation before making endpoints public, weakening auth, or introducing speculative compatibility layers.
12. Produce final compliance report:
   - Implemented behavior, intentionally unsupported behavior + correct error, known spec ambiguities, and prioritized next tasks.

# Examples
- Positive trigger: "Implement `message/send` and `GetTask` for our Home Assistant A2A bridge with correct task states and errors."
- Positive trigger: "Review this Agent Card and streaming implementation for capability-gating compliance."
- Positive trigger: "Add `A2A-Version` handling and `VersionNotSupportedError` behavior for unsupported versions."
- Positive trigger: "Validate that `SubscribeToTask` sends current `Task` first and preserves event ordering."
- Negative trigger: "Improve dashboard layout for assistant controls." (not this skill)
- Negative trigger: "Only review if tests have enough edge cases for parser fuzzing." (use `qa-coverage`)

# Limitations
- This skill does not replace official spec/proto reading when behavior is ambiguous.
- This skill does not choose product-level compatibility policy; it enforces whichever policy is explicitly decided.
- This skill does not perform comprehensive non-A2A architecture redesign.
- This skill assumes you can access the target code and run the project test suite.
- This skill does not provide legal/security certification; it only enforces protocol and engineering correctness.

# Self-test
- Routing tests (should trigger this skill):
  - "Implement `message/stream` with `TaskStatusUpdateEvent` ordering guarantees."
  - "Map Home Assistant conversation responses into A2A `Artifact.parts` and task updates."
  - "Validate that unsupported push notifications return the right protocol error."
  - "Add Agent Card generation with truthful capability flags and per-assistant identities."
  - "Review our A2A server for proto/schema mismatch risks before release."
- Routing tests (should NOT trigger this skill):
  - "Find dead code in this integration and propose safe removals." -> use `unused-code-scan` / `dead-code-officer`
  - "Assess whether our tests adequately cover cancellation and stream disconnect edge cases." -> use `qa-coverage`
  - "Write README onboarding docs for contributors." -> use `doc-writing`
- Execution tests:
  - Expected output shape:
    - Operation coverage table (implemented vs unsupported-with-correct-error vs pending).
    - Object/field mapping notes tied to `a2a.proto` names.
    - Capability/error matrix with concrete failure behavior.
    - Lifecycle and streaming contract verification checklist.
    - Test checklist including success and failure cases.
    - Explicit list of unresolved protocol ambiguities.
  - Common failure modes:
    - Treating docs/examples as normative when proto conflicts.
    - Declaring capability flags without implementing matching methods.
    - Returning generic errors instead of A2A-specific error semantics.
    - Losing stream event ordering or terminal-state close semantics.
    - Using ad-hoc dict transforms that drift from model schema.
    - Returning incorrect pagination tokens or including forbidden omitted fields.
  - Correction strategy:
    - Re-anchor on `a2a.proto`, regenerate the operation/error matrix, then fix one mismatch class at a time (schema -> capability gating -> lifecycle/stream ordering -> tests).
