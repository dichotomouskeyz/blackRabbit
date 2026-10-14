# Recording investigation agent

Approved implementation plan: 2026-10-13. The user requested a headless portfolio
implementation with credentials deferred. No live model calls are required.
This contract supersedes frontend-shell's local-only model policy only for the
new optional Python agent. The existing frontend remains unchanged.

## Behavior

- RI-001: One PydanticAI agent exposes exactly six read/analysis tools:
  list_sessions, get_session_summary, list_events, get_event_response,
  inspect_signal_window and get_recording_quality. Tools are SDK-independent.
- RI-002: Sponsor/site identity and the selected session come from trusted
  dependencies. All SQL uses fixed table mappings and bound values through a
  SELECT-only connection. Model arguments cannot set identity, SQL or URLs.
  Default database connection attempts have a five-second connect timeout,
  including when the configured read-only URL omits or extends that timeout.
- RI-003: Investigation requires a closed, watermark-verified session with a
  saved ARC report. Pin that report's analysis ID/hash for the conversation.
  No tool updates capture, analysis, raw signals or audit records.
- RI-004: Event responses expose the saved ARC windows, units, baseline values,
  exclusions, p/q values and provenance. New descriptive window statistics are
  exploratory and cannot substitute for or recalculate saved significance.
- RI-005: Inspect at most 600 seconds and 1,000,000 rows per window, using a
  bounded SQL statement timeout. Reject invalid/reversed/nonfinite bounds and
  unknown modality/channel names. Preserve gaps and quality flags in chart data.
  Charts have at most 2,000 points per channel and never enter model context.
  Inspect at most 64 channels and 600 feature epochs, with saved epoch duration
  at least one second. Cooperative budget checks run through sample, epoch,
  component and channel loops within a 12-second numerical budget. Full-window
  EEG features require every channel declared in recording metadata; an
  explicitly selected channel uses that channel alone. Missing declared channels
  are reported and exclude full-window features; undeclared channels are rejected.
- RI-006: Each returned measurement receives a server-issued evidence ID with
  session, analysis, event, window, metric and value provenance as applicable.
  Final findings reference only evidence produced by this investigation.
  Unknown references cause validation failure; raw free text is untrusted data.
- RI-007: Defaults are eight model requests, ten successful tool calls, one
  retry and a 90-second actual-run timeout. Provider transport retries are
  bounded separately. Timeouts/cancellation preserve failure or partial state,
  never a fabricated completed report.
- RI-008: Model selection is server-side OpenAI or Anthropic, explicitly
  configured without fallback. Importing the ordinary backend requires neither
  the agent SDK nor credentials. Missing optional setup returns a structured 503.
- RI-009: POST /agent/chat uses the AI SDK 7 stream protocol. Inputs contain a
  user message, selected session ID and optional conversation ID only. Reject
  supplied system/assistant/tool history, provider choice and tenant identity.
  Conversation history is server-owned, tenant/session-bound, single-process,
  limited to 20 retained messages and expires after 30 idle minutes. Serialize
  a conversation's turns; reject overlap with 409. Retain at most 64 conversations
  and trim history by complete SDK turns. Failed or cancelled turns invalidate
  the conversation, preventing unfinished workers from racing a later turn.
  Evidence is bounded to 10,000 entries and tool trace to 100 entries per
  conversation; charts are drained when streamed. Streaming uses no-store.
- RI-010: Final output contains summary, findings, evidence, quality limitations
  and unresolved questions. Tool activity and bounded charts are streamed for a
  later frontend. Report citations resolve to canonical server measurements.
  Recording quality returns counts covering all saved events and windows, with
  details for at most 20 events. Truncation and omitted event counts are explicit;
  the pinned saved report remains unchanged and event response reads retain the
  selected event's complete saved details.
- RI-011: CLI runs the same agent/tools; offline demo uses FunctionModel and
  conspicuously identifies itself as scripted, with synthetic input and no live
  model. Live-provider intelligence is not claimed by passing offline tests.
- RI-012: Tests disable model network requests globally. Verify actual SDK
  loop/tool calls, both provider constructions using fake credentials without
  network calls, malformed arguments, missing/foreign data, report pinning,
  numerical bounds, evidence validation, loop limits, cancellation and expiry.

## Interface defaults

POST /agent/chat request: {message: string (1..4000 characters), session_id: UUID,
conversation_id?: UUID}. Response is SSE with conversation/run metadata, SDK
tool events, chart data and structured final report. Unavailable configuration
503, invalid input 422, foreign/missing resource 404, lifecycle or busy 409.
The initial CLI is `python -m investigation --help`.

The optional installation extra is `agent`; base capture/install remains valid.
No frontend changes, migrations, model credentials, persistent chat storage,
capture controls, cross-session comparison, arbitrary code or public deployment.
