# Resume Agent model evaluation

This directory contains an **opt-in** evaluation suite for the configured
resume Agent model. The real-provider runner is not invoked by the application,
normal `pytest`, or CI. The runner calls a real configured provider, so results
can vary with the model and network. Normal test discovery only runs the
offline mock-provider validation.

## Run

From `backend/`:

```bash
.venv/bin/python scripts/agent_model_eval.py
```

The default enabled model is used. Select another configured model by its
client id:

```bash
.venv/bin/python scripts/agent_model_eval.py \
  --model-config-id YOUR_MODEL_CONFIG_ID
```

Run selected cases or save the JSON report:

```bash
.venv/bin/python scripts/agent_model_eval.py \
  --case advice_only_no_edits \
  --case current_attachment_boundary \
  --output /tmp/resumate-agent-model-eval.json
```

Exit codes:

- `0`: every selected case passed.
- `1`: the runner completed and one or more model cases failed.
- `2`: the fixture, configuration, or runner could not start.

## Boundaries

- The script reuses `resolve_agent_llm_config` and the production Agent tool
  loop. It does not define another prompt or tool protocol.
- Reports contain provider/model names and behavioral counters, but never
  serialize model configuration or API keys. Error strings are redacted.
- Attachment cases use synthetic text files in an evaluation-only session.
  Current and historical files are materialized separately and removed after
  each case, including failed cases.
- A `provisional` result means edits were exposed as a user-confirmable draft.
  The runner's internal atomic transaction may be `committed`; that does not
  mean the draft was applied to the user's saved resume.
- This suite is a diagnostic model check, not a deterministic merge gate.
  Provider drift and transient network failures should be reviewed in the
  machine-readable `failureReasons`.

## Fixture shape

`scenarios.json` is versioned. Each case provides an `AgentChatRequest` subset,
optional synthetic attachments, and observable expectations such as edit
count, public transaction state, required evidence, forbidden claims, and
tool-error count for the transaction-repair scenario.

The offline unit test only mocks the provider boundary and verifies runner
selection, reporting, and secret redaction:

```bash
.venv/bin/pytest tests/model_eval/test_agent_model_eval.py
```
