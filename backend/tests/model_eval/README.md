# Resume Agent model evaluation

This directory contains an **opt-in** evaluation suite for the configured
resume Agent model. The real-provider evaluator is not invoked by the
application, normal `pytest`, or CI. It calls a real configured provider, so
results can vary with the model and network. Normal test discovery only runs
the offline mock-provider validation.

## Run

From `backend/`:

```bash
uv run --locked python scripts/agent_model_eval.py
```

The default enabled model is used. Select another configured model by its
client id:

```bash
uv run --locked python scripts/agent_model_eval.py \
  --model-config-id YOUR_MODEL_CONFIG_ID
```

Run selected cases or save the JSON report:

```bash
uv run --locked python scripts/agent_model_eval.py \
  --case advice_only_no_edits \
  --case current_attachment_boundary \
  --output /tmp/resumate-agent-model-eval.json
```

Exit codes:

- `0`: every selected case passed.
- `1`: the evaluator completed and one or more model cases failed.
- `2`: the fixture, configuration, or evaluator could not start.

## Boundaries

- The script reuses `resolve_agent_llm_config` and the production Agent tool
  loop. It does not define another prompt or tool protocol.
- Reports contain provider/model names and behavioral counters, but never
  serialize model configuration or API keys. Error strings are redacted.
- Attachment cases use synthetic text files in an evaluation-only session.
  Current and historical files are materialized separately and removed after
  each case, including failed cases.
- A `committed` transaction means `ResumeToolEnvironment` naturally completed
  and published the `DraftEditEngine` result as a user-confirmable draft. It
  does not mean the draft was applied to the user's saved resume.
- This suite is a diagnostic model check, not a deterministic merge gate.
  Provider drift and transient network failures should be reviewed in the
  machine-readable `failureReasons`.

## Auto quality metrics

Report schema version 5 includes provider-independent runtime metrics for
comparing configured models on the same fixture:

- `editAccuracy` checks requested edit counts, targets, payload evidence, and
  transaction completion for cases that produced an observable result.
- `toolCompletion` checks the finalized environment transaction state, tool
  errors, and declared tool sequence. Completion is the model's natural answer
  after its last observation; it is not a tool protocol.
- `hallucination` counts forbidden claims only in cases that declare grounded
  evidence constraints and produced an observable result. Provider execution
  failures remain failures, but are not mislabeled as hallucinations.
- `truncation` is derived from the normalized provider stop reason, including
  failed cases whose partial response cannot be used.
- `latencyMs` measures the complete case execution time.
- `tokenUsage` sums normalized input, output, reasoning, cache-read, and
  cache-write tokens across the tool loop, conversation compaction, and final
  reply. `requestAttempts` counts outbound provider transport attempts,
  including timeout retries and the OpenAI-compatible parallel-tool fallback;
  `terminalResponses` counts only completed provider messages. Each token
  field reports its own response coverage and is complete only when every
  terminal response supplied that field.
- Each case's `observed` diagnostics include `toolErrorCodeSequence` and
  `toolErrorCodeCounts`. They contain only stable internal codes, never tool
  inputs, resume text, rejection reasons, or provider error text.

`requestAttempts` covers attempts explicitly dispatched by ResuMate. A
provider SDK may perform opaque transport retries internally; those cannot be
reported separately unless the SDK exposes them.

`cost` is deliberately reported as `unavailable`. Model discovery does not
provide authoritative, effective-dated prices, so the evaluator does not guess
cost from a model-name pricing table. Use the provider billing report alongside
the emitted token counts when a cost comparison is required.

## Fixture shape

`scenarios.json` is versioned. Each case provides the canonical
`AgentChatRequest.message` for the current user turn, optional prior
`messages`, synthetic attachments, and observable expectations. Response and
edit text are asserted in separate domains; edit targets, finalized transaction
state, and exact tool order can also be required. Opportunity-specific cases
assert visible response or draft evidence directly. Forbidden response regular
expressions keep employment-only language such as CAR, ATS, or commercial
impact out of academic application advice.

Every fixture resume is validated against the same exact ResumeDocument
contract used by production before any provider call. Enrichment cases can
also require a minimum number of distinct highlights, so a longer synonym-only
rewrite cannot masquerade as a meaningfully richer experience. Required fact
markers and forbidden ownership, metric, or outcome patterns remain separate
assertions; this measures evidence-preserving density rather than raw length.

`current_web_jd_tailoring` exercises the production search path: hosted search
for supported cloud providers, otherwise the local DuckDuckGo/HTTP/Chromium
tools. It requires a readable current JD before one grounded summary edit and
requires the final answer to name and cite the selected role. Source count
proves either search path produced readable evidence; the visible tool sequence
requires only the provider-neutral `edit_execute` action.

The offline unit test only mocks the provider boundary and verifies evaluator
selection, reporting, and secret redaction:

```bash
uv run --locked pytest tests/model_eval/test_agent_model_eval.py
```
