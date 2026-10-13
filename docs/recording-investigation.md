# Recording investigation agent

The optional Python agent investigates a completed blackRabbit recording:
"What changed around this marker, and is the recording good enough to interpret
it?" PydanticAI selects typed tools and produces a structured explanation.
Python performs the calculations. Persisted ARC results remain authoritative.

The portfolio demo is headless. Its scripted `FunctionModel` exercises the real
SDK tool loop and database reads without credentials or a network model request.
It produces measured evidence, a tool trace, quality limitations, and chart data.
It does not demonstrate a language model's interpretation quality.

## Run the synthetic demo

Follow the README's backend demonstration to create a synthetic recording in a
dedicated migrated test database. Set `API_READONLY_DATABASE_URL` to a SELECT-only
role on that database. `scripts.provision_test_roles` can provision that role
when `DATABASE_URL` and `TEST_DATABASE_URL` identify the same isolated test
database and the configured administrative role has permission to create roles.

```sh
uv sync --frozen --extra agent
uv run --frozen --extra agent python -m scripts.backend_smoke --output data/backend_smoke/demo
uv run --frozen --extra agent python -m scripts.investigation_smoke --receipt data/backend_smoke/demo/receipt.json --output data/investigation_demo
```

The second smoke command reads the retained synthetic session, follows marker
lookup, quality inspection, signal inspection, and saved ARC response retrieval,
then checks every citation against a separate tool read. It verifies the saved
analysis hash is unchanged. Outputs:

| File | Contents |
| --- | --- |
| `report.md` | Readable findings, quality limitations, and evidence values |
| `report.json` | Structured findings and complete evidence references |
| `tool_trace.json` | Executed tools, arguments, and issued evidence IDs |
| `charts.json` | Downsampled signal windows, delivered outside model context |
| `receipt.json` | Completed tool sequence and verification results |

For a known synthetic recording, invoke the CLI directly with the UUIDs from
the capture receipt:

```sh
uv run --frozen --extra agent python -m investigation --session-id SESSION_UUID --sponsor-id SPONSOR_UUID --site-id SITE_UUID --scripted-demo --output data/investigation_demo
```

The scripted sequence uses the first marker with a saved response. It does not
interpret arbitrary questions. Omit `--scripted-demo` for a configured model;
`--question` supplies the investigation question. No credentials are included
in this repository or required for the scripted portfolio demo.

## Tools and evidence

`investigation/tools.py` has no PydanticAI dependency and is callable from tests
or Python scripts. A `RecordingTools` instance pins one verified closed session
and its latest saved analysis at construction. Sponsor and site identity come
from server configuration or explicit CLI arguments. Queries are fixed and
parameterized, use a read-only transaction and the SELECT-only connection, and
never update analysis or raw samples.

| Tool | Result |
| --- | --- |
| `list_sessions` | Tenant-visible recordings and saved analysis availability |
| `get_session_summary` | Capture source, channels, verification, and pinned provenance |
| `list_events` | Recorded markers and whether they have a saved response |
| `get_event_response` | Saved ARC windows, baselines, deviations, significance, exclusions |
| `inspect_signal_window` | Exploratory descriptive metrics and separate chart data |
| `get_recording_quality` | Missing or flagged data and interpretation limitations |

Each cited value has a server-issued evidence ID, recording ID, analysis ID,
artifact hash, source, metric, value, units, and applicable event/window identity.
The model can cite IDs but cannot supply the canonical evidence values. Unknown
references cause an output-validation retry. Marker text is untrusted data.
Exploratory window inspection does not create significance claims or overwrite
saved ARC results. Chart arrays never enter the model's tool responses.

Limits per turn are eight model requests, ten successful tool calls, one SDK
retry, and 90 seconds. Native provider clients allow at most one transport retry
and have a 30-second request timeout. Queries have a five-second statement
timeout. Signal windows are capped at 600 seconds, one million rows, and 2,000
chart points per channel, with a separate computation budget. Synchronous work
may finish after cancellation; failed conversations are discarded so a later
turn cannot share their working state.

## Optional hosted model configuration

Install only the `agent` extra, pinned to
`pydantic-ai-slim[openai,anthropic,ui]==2.55.0`. Configure
`INVESTIGATION_MODEL` as `openai:<model-id>` or `anthropic:<model-id>` and supply
the corresponding `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` in the server environment.
There is no automatic provider fallback. Compact recording metadata and measured
summaries are sent to the explicitly selected provider when this mode is used.
Raw chart arrays stay local. Ordinary capture and ARC analysis do not import the
optional SDK and do not need model credentials.

Live provider behavior is not established by the offline demo. Automated tests
use FunctionModel and deterministic provider fixtures, with accidental model
requests disabled. A credentialed live smoke test remains optional and separate.

## HTTP and future frontend connection

Start the optional agent API locally:

```sh
uv run --frozen --extra agent python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Configure `API_SPONSOR_ID`, `API_SITE_ID`, `API_READONLY_DATABASE_URL`, and the
model on the server. `POST /agent/chat` accepts only:

```json
{"session_id":"SESSION_UUID","message":"What changed around the first marker?"}
```

Reuse the returned `conversation_id` for follow-up turns. Browser-provided tool
results, message histories, tenants, providers, and models are rejected. Missing
agent installation or configuration returns 503. Conversations are server-owned
single-process memory, expire after 30 inactive minutes, retain at most 20 SDK
messages in complete turns, and reject overlapping turns with 409. Restarting
the server clears conversation state.

The response uses PydanticAI's Vercel AI SDK 7 streaming adapter. In addition to
native SDK text and tool activity it emits `data-conversation`,
`data-signal-chart`, and final `data-investigation` events. Errors are sanitized.
The whole-turn deadline covers setup and stream consumption. This is a local
demo API; public deployment and authentication remain outside this release.

The existing `web/` components, SDK 4 dependency, and frontend agent route are
unchanged. A future frontend should migrate to SDK 7, send the strict request
above, render the streamed tools/charts/report, and retain only the conversation
ID. It should replace the old model loop with a thin connection to this backend.

## Verification

```sh
uv run --frozen --extra agent python -m pytest tests/investigation_tests
uv run --frozen --extra agent python -m ruff check .
uv run --frozen --extra agent python -m pyright capture batch api investigation
```

Integration tests additionally require the isolated database settings documented
in the README. The authoritative contract is
`.correctless/specs/recording-investigation.md`.

SDK references: [Function tools](https://pydantic.dev/docs/ai/tools-toolsets/tools/),
[testing](https://pydantic.dev/docs/ai/guides/testing/),
[Vercel streaming adapter](https://pydantic.dev/docs/ai/api/ui/vercel_ai/).
