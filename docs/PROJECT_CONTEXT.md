# Reseno Project Overview

English | [简体中文](PROJECT_CONTEXT_ZH.md)

## Product scope

Reseno is a self-hosted, single-owner resume workspace with structured editing,
templates, import and export, and Agent-assisted edits. Workspace data stays on
the instance, while model requests use the services configured by the owner.
Each instance has one account, with no collaboration or multi-tenant workspaces.

See the [README](../README.md) for installation, startup and configuration, and
the [API reference](API.md) for HTTP interfaces and data contracts. This document
covers product behavior, module responsibilities and runtime constraints.

| Capability | Current behavior |
| --- | --- |
| Account | Initial owner setup; password login and optional binding to the instance's own GitHub App; session synchronization across same-origin tabs; reauthentication during editing lets the user resume their work |
| Resumes | Creation, duplication, search, pagination, structured editing, autosave, manual checkpoints, version history and a recycle bin |
| Editing | Basic information, avatar cropping and custom contact fields; education, experience, projects, publications, achievements and generic lists; section reordering, collapsing and inline rich text |
| Templates | Six built-in templates: Minimal, Modern, Compact, Classic, Executive and Academic; custom copies with editable layout, fonts, colors and decorative images |
| Preview | Shared A4 rendering, pagination and zoom; template try-on, image positioning, one-page fitting and Agent draft diff previews |
| Import and export | Resume and template JSON import, PDF parsing in the browser; cancellable imports that retain successful items and support retries; JSON, PDF, single-page PNG and multi-page image ZIP export |
| Agent | Chat, attachments, model selection, public web search, structured edit drafts, item-by-item review, continued editing, cancellation and reconnection |
| Language and appearance | Chinese and English interfaces; resume language independent of UI language, with default templates saved per resume language; light, dark and system themes |

PDF import extracts readable text and parses its structure. It cannot guarantee
reconstruction of every layout or scanned image as the original document.
Agent output quality depends on the supplied facts, the model and external
information. Proposed edits form a reviewable draft for the user to confirm.

## Modules and entry points

The frontend uses React, TypeScript, Vite, Tailwind CSS and shadcn/ui, with pnpm
for package management. The backend uses Python, FastAPI, SQLite and uv.

| Location | Responsibility |
| --- | --- |
| [frontend/src/App.tsx](../frontend/src/App.tsx) | Authentication entry points, routes and page loading boundaries |
| [frontend/src/components/workspace](../frontend/src/components/workspace) | Page queries, route transitions, saving and leave transactions |
| [frontend/src/components/editor](../frontend/src/components/editor) | Structured resume editing and rich text input |
| [frontend/src/components/preview](../frontend/src/components/preview) | Document preview and pagination shared by resumes, templates and exports |
| [frontend/src/components/templates](../frontend/src/components/templates) | Template catalog and custom template editing |
| [frontend/src/components/copilot](../frontend/src/components/copilot) | Agent sessions, streaming events, draft review and run state |
| [frontend/src/lib](../frontend/src/lib) | API clients, domain operations, import and export, authentication and shared state logic |
| [backend/app/main.py](../backend/app/main.py) | The `create_app` application factory and resource lifecycle |
| [backend/app/routers](../backend/app/routers) / [schemas](../backend/app/schemas) | HTTP routes, request validation and response models |
| [backend/app/services](../backend/app/services) | Persistence for resumes, templates, authentication, exports, model configurations and sessions |
| [backend/app/services/agent](../backend/app/services/agent) | Model context, the open-ended tool loop, evidence boundaries and draft transactions |
| [backend/app/services/llm](../backend/app/services/llm) | Request, streaming response and parameter adaptation for each API family |

The main pages are `/setup`, `/login`, `/resume`, `/resume/:id`, `/templates`,
`/template/:id`, `/trash`, `/models` and `/settings`. `/auth/callback` handles
sign-in returns, and `/pdf-export` renders frontend documents for server-side
Chromium.

Workspace pages load their initial data through the corresponding aggregated
queries under `/api/workspace/pages/*`. Subsequent reads and writes use the
resume, template, model and Agent resource endpoints. Page queries do not persist
business state. Frontend domain clients reuse
[api-client.ts](../frontend/src/lib/api-client.ts) and its authentication, error
handling and request core; components do not define a separate communication
protocol.

## Data and save semantics

The resume body is a structured document with `schemaVersion: 2`, containing
`basic` and `sections`. Sections are distinguished by `kind`: `education`,
`experience`, `project`, `publication`, `achievement` or `simple_list`. Each kind
has its own item fields. A generic list is stored as a single rich text item with
`content`; its internal bullets are not split into separate resume items.
Supported rich text is normalized consistently and cannot execute arbitrary HTML.

The resume resource also stores its title, `documentLocale`, job description,
typography, template ID and resume-level template settings overrides. Template
presets, layouts, typography and visual settings belong to a separate resource.
Built-in templates are read-only; custom copies are editable.

- Resume autosave retains only the latest temporary version. Manual saves create
  checkpoints, and the version list shows those checkpoints. Saving identical
  content does not create duplicate versions.
- Custom template autosave preserves the explicitly saved checkpoint. Manual
  saving confirms the current template; discarding changes restores the checkpoint.
- Export saves the current resume first, then reads the document using the
  returned version identifier to avoid exporting stale content.
- Moving a resource to the recycle bin and permanently deleting it are separate
  operations. Permanent deletion requires the resource to already be marked deleted.
- The browser retains authentication sessions, UI preferences and active editing
  state. The backend manages persistent workspace data.

## Authoritative contracts

| Contract | Authoritative file | Frontend entry point |
| --- | --- | --- |
| Resume document | [resume_document.schema.json](../backend/app/services/resume_document.schema.json) | [types/resume.ts](../frontend/src/types/resume.ts) |
| Section kinds and fields | [section_registry.json](../backend/app/services/agent/section_registry.json) | `/api/section-registry` and [resume-sections.ts](../frontend/src/lib/resume-sections.ts) |
| Agent edit operations | [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) | [resume-edit-operation.generated.ts](../frontend/src/types/resume-edit-operation.generated.ts) |
| Built-in templates | [template_presets.json](../backend/app/services/template_presets.json) | [template-presets.generated.ts](../frontend/src/lib/template-presets.generated.ts) |
| HTTP requests and responses | [backend/app/schemas](../backend/app/schemas) and route implementations | [types/api.ts](../frontend/src/types/api.ts) and domain clients |

Run `pnpm generate:agent-contract` and `pnpm generate:template-presets` from
`frontend` to update the corresponding generated files. Documentation explains
behavior and usage; these contracts define the full fields and operation variants.

## Agent and models

The Agent's primary output is a draft that can be previewed, applied or discarded.
Using the current document, user input, attachments and session context, the model
chooses whether to answer directly or call tools. Tool results return to the same
loop, and the turn completes when the model finishes naturally. The system does
not enforce a fixed sequence of analysis, search, editing and summary stages.

Local tools include `web_search`, `web_fetch` and `edit_execute`. When provider-native
search is enabled, it replaces the local web tools. The editing tool is unavailable
in `suggestOnly` mode. Public web pages are external references and cannot serve
as factual evidence of the candidate's responsibilities, metrics or experience.
Personal information is redacted in model context, and the edit engine validates
privacy, factual provenance and document structure. See
[runtime](../backend/app/services/agent/runtime),
[environment.py](../backend/app/services/agent/environment.py) and
[draft/engine.py](../backend/app/services/agent/draft/engine.py) for context and tool
behavior.

Edit batches enter `provisional` state first. A successful turn produces a
`committed` draft awaiting review; this commit only completes the Agent transaction.
Changes to the saved resume still require user review and confirmation.
Cancellation, unresolved tool rejection or run failure rolls back the unfinished
transaction. Session revisions reject concurrent overwrites. Continued editing of
a draft retains the original baseline for diff comparison and conflict handling.

Chat uses SSE, and clients resume subscriptions by event sequence number. An HTTP
disconnection does not automatically cancel an accepted run. Sessions and final
execution states are persisted; active model requests and event replay buffers
belong to the current process. Backend restarts do not resume the original provider
request.

Model configuration distinguishes cloud providers, local runtimes and custom APIs.
`provider` identifies the service, while `apiFamily` selects the `openai_responses`,
`openai_compatible_chat`, `anthropic_messages` or `google_gemini` adapter. The
provider catalog and default URLs come from
[model_providers.py](../backend/app/services/model_providers.py).

Model discovery results and supplementary capability metadata are cached separately.
Supplementary metadata comes from a merged snapshot of LiteLLM and models.dev.
Metadata describes capabilities; protocol adapters implement the actual request
format. Thinking uses `thinkingMode: auto | off`, with the supported choices
returned in `availableThinkingModes`. Off is available only when both the model's
capabilities and protocol adapter support it. API keys are encrypted on the backend;
clients receive only a preview value.

## Runtime and data constraints

The application factory initializes configuration and keys. The application
lifecycle handles database validation, recovery operations and resource cleanup.
The default data directory is `~/.reseno`: `app.db` stores workspace data,
`auth.db` stores account and authentication data, `storage` holds documents,
attachments and temporary exports, and `user_settings.json` stores user settings.
See [backend/.env.example](../backend/.env.example) for path overrides.

Missing encryption and signing keys are written to the configuration file on first
startup. If an existing database lacks its keys, the original keys must be restored.
Backups must retain the configuration keys, databases and storage together. When
startup validation finds an incompatible database structure, it preserves the data
and refuses to start; it does not automatically migrate or rebuild an existing
database.

Use one worker and one replica per workspace. While running, the backend holds
exclusive file locks on the workspace database, authentication directory and
storage directory. Storage must support those lock semantics. The process manages
Agent runs and the renderer.

The backend reuses Chromium to render PDFs and images serially, with an isolated
browser context per request. At most four export requests may be running or queued
in total. The renderer accesses `/pdf-export` under `FRONTEND_RENDER_BASE_URL`;
production static hosting must support direct access to that route and SPA fallback.
Serve the frontend and `/api` through a same-origin proxy where possible. Remote
GitHub sign-in requires HTTPS. Initial owner creation accepts only loopback clients.
Export downloads require authentication, and temporary files expire.

Public Swagger, ReDoc and `/openapi.json` endpoints are disabled. Internal tooling
can read the generated HTTP schema from the application instance's `app.openapi()`.

## Development and verification

Dependency versions are defined by
[frontend/package.json](../frontend/package.json),
[backend/pyproject.toml](../backend/pyproject.toml) and their lockfiles. The
[quality workflow](../.github/workflows/frontend-quality.yml) uses Node 24,
pnpm 11.9.0 and Python 3.13. The Python project requires at least Python 3.12.

| Working directory | Command | Purpose |
| --- | --- | --- |
| `frontend` | `pnpm install --frozen-lockfile` | Install locked frontend dependencies |
| `frontend` | `pnpm check:frontend` | Check formatting, source budgets, lint, types, behavior and production bundle budgets |
| `frontend` | `pnpm test:workspace-network:smoke` | Run key workspace browser regressions |
| `backend` | `uv sync --locked --all-groups` | Install locked backend and development dependencies |
| `backend` | `uv run --locked ruff check .` | Run Python static checks |
| `backend` | `uv run --locked mypy app` | Check Python types |
| `backend` | `uv run --locked pytest -q` | Run the default backend test suite |
| `backend` | `RUN_BROWSER_E2E=1 uv run --locked pytest tests/e2e -q` | Run the full browser test suite |

Browser tests require Playwright Chromium. Tests skipped because `RUN_BROWSER_E2E=1`
is not set do not count as passing validation. The CI smoke suite and full E2E suite
cover different scopes. Tests use isolated data directories. Start frontend and
backend services from `frontend` and `backend`, respectively.
