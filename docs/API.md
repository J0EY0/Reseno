# Reseno API

English | [简体中文](API_ZH.md)

This document describes the HTTP interface between the frontend and the FastAPI backend. The default base URL is the same-origin `/api`; Vite proxies requests to the backend during development. Set `VITE_API_BASE_URL` to override the frontend API base URL and `VITE_DEV_API_TARGET` to override the development proxy target. See the [README](../README.md) for startup, secret, and storage configuration.

## Contract sources

Response types in the tables below refer to the JSON envelope's `data` field, except for endpoints marked as SSE, file, HTML, or redirect responses. JSON fields use the aliases declared in the schemas, such as `documentLocale` and `savedAt`.

| Subject | Exact fields and implementation |
| --- | --- |
| HTTP routes, query parameters, and status codes | [backend/app/routers](../backend/app/routers) |
| Request and response validation | [backend/app/schemas](../backend/app/schemas) |
| Frontend API types | [frontend/src/types/api.ts](../frontend/src/types/api.ts) |
| Resume document structure | [resume_document.schema.json](../backend/app/services/resume_document.schema.json) |
| Agent edit operations | [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) |
| Frontend resume, template, and workspace types | [frontend/src/types/resume.ts](../frontend/src/types/resume.ts) |
| Built-in template definitions | [template_presets.json](../backend/app/services/template_presets.json) |

The service is created through `app.main:create_app`. `/docs`, `/redoc`, and `/openapi.json` are not exposed; contract tooling can call `app.openapi()` on the application object. Consult the corresponding implementations for SSE, manually constructed file responses, and authentication middleware rules.

## HTTP and authentication conventions

A standard successful JSON response is:

```json
{
  "code": 0,
  "message": "OK",
  "data": {},
  "requestId": null
}
```

`requestId` can be null or omitted. `message` is a stable message identifier localized by the client. Errors retain their actual HTTP status; failures are not reported as HTTP 200.

| HTTP status | Meaning | Common `code` |
| --- | --- | --- |
| 2xx | Success | `0` |
| 400, 403, 409, 413, 429 | Invalid request, forbidden operation, conflict, oversized upload, or insufficient run capacity | `40000` |
| 401 | Login failure or invalid session | `40001` |
| 404 | Resource not found | `40004` |
| 422 | Invalid request structure or fields | `40002` for request model validation |
| 5xx | Server or upstream error | `50000` |

Pydantic request validation failures return `message: "VALIDATION_ERROR"`, with field errors in `data.errors`. Manually raised HTTP errors are mapped by HTTP status; for example, invalid Agent session replacement uses HTTP 422, `code: 40000`, and `message: "AGENT_SESSION_REPLACEMENT_INVALID"`. See [exceptions.py](../backend/app/exceptions.py) for the complete rules.

Protected endpoints require:

```http
Authorization: Bearer <accessToken>
```

The [authentication middleware](../backend/app/middleware/auth.py) exempts only these actual API paths from Bearer validation:

- `/api/auth/setup`
- `/api/auth/login`
- `/api/auth/oauth/github/login`
- `/api/auth/oauth/github/callback`
- `/api/auth/oauth/github/setup/callback`
- `/api/auth/oauth/complete`

`OPTIONS` requests also bypass Bearer validation. GitHub callbacks and code exchange still validate OAuth flow state and the browser session; public access does not mean validation is skipped. `/health` is outside the API prefix.

When the authentication middleware rejects a request, it returns HTTP 401, `WWW-Authenticate: Bearer`, and:

```json
{
  "code": 40001,
  "message": "UNAUTHORIZED_REQUEST",
  "data": {
    "loginUrl": "/login",
    "reason": "invalid_or_expired_token"
  },
  "requestId": null
}
```

`reason` is `missing_token`, `invalid_or_expired_token`, or `owner_missing_or_changed`. An incorrect password uses `INVALID_CREDENTIALS`. Clients should handle errors by status code and message identifier, without depending on English error sentences.

The JSON envelope does not apply to Agent SSE, attachment and export file downloads, OAuth HTML/303 callbacks, or `/health`. Errors from `/api/*` endpoints that reach the shared exception handlers use the JSON error envelope. OAuth flow failures use the corresponding callback format; run errors after an SSE stream has been established are reported through stream events.

## Owner and login sessions

Contracts: [auth.py schema](../backend/app/schemas/auth.py), [auth routes](../backend/app/routers/auth.py), and [auth_tokens.py](../backend/app/services/auth_tokens.py). An instance has one owner, with no public registration or default password.

| Method | Path | Request | Response and behavior |
| --- | --- | --- | --- |
| GET | `/api/auth/setup` | None; public | `AuthSetupStatusResponse`: `setupRequired`, `githubLoginAvailable`; `Cache-Control: no-store` |
| POST | `/api/auth/setup` | `AuthSetupRequest`: `username`, `password`, `confirmPassword`; public | Creates the sole owner from a loopback client and returns `AuthLoginResponse`; 403 for non-local clients, 409 if already initialized |
| POST | `/api/auth/login` | `AuthLoginRequest`: `username`, `password`; public | `AuthLoginResponse`; 401 for invalid credentials |
| POST | `/api/auth/refresh` | Valid Bearer; no body | `AuthLoginResponse`; renews the session and revokes the old token |
| POST | `/api/auth/username` | `AuthUsernameUpdateRequest`: `newUsername`, `currentPassword`; valid Bearer | `AuthLoginResponse`; changes the username after verifying the current password; 400 for an invalid username or password, 401 if the session is invalid or the owner has changed |
| POST | `/api/auth/password` | `AuthPasswordUpdateRequest`: `currentPassword`, `newPassword`, `confirmPassword` | `AuthPasswordUpdateResponse`: `username`, `updated: true`; 400 for an incorrect current password |

After trimming surrounding whitespace, usernames must contain at least 3 characters and may use only ASCII letters, digits, `_`, and `-`. New passwords must contain at least 8 characters, including ASCII letters and digits, and must match the confirmation value. Initial setup checks the client address received by the backend.

`AuthLoginResponse` contains `username`, `accessToken`, `expiresAt`, and `tokenType: "bearer"`. JWTs expire 36 hours after issuance; renewal requires the old token to remain valid. The old token's `jwt_id` and original expiry time are stored in `auth_revoked_tokens` in `auth.db`, so revocation survives backend restarts. Each token can be renewed successfully only once.

A username update verifies the current owner and the request's authentication revision, checks the current password, and updates the username and authentication revision in one transaction. The transaction commits only after replacement credentials have been issued successfully. An actual rename invalidates all existing JWTs; the client continues the session with the new credentials in the response. Reverting to a previous username does not restore old JWTs. A request whose trimmed username matches the current username still validates the session and password, but does not update the owner or authentication revision, and returns fresh valid credentials. Renaming preserves the current password, linked GitHub identity, and resume data; subsequent login uses the new username and the original password.

A password update changes the owner's authentication revision, invalidating all existing JWTs. The frontend stores the session in same-origin localStorage and coordinates renewal, login, and logout across tabs. Client logout clears the local session; there is no separate server logout endpoint. See [auth.ts](../frontend/src/lib/auth.ts) and [auth-session.ts](../frontend/src/lib/auth-session.ts) for the session client.

### GitHub App and identity linking

Contracts: [auth_oauth.py](../backend/app/routers/auth_oauth.py) and [auth.py schema](../backend/app/schemas/auth.py). `provider` currently accepts only `github`.

| Method | Path | Request and authentication | Response |
| --- | --- | --- | --- |
| GET | `/api/auth/oauth/identities` | Bearer | `OAuthIdentitiesResponse`: linked `identities` and provider configuration status in `providers` |
| POST | `/api/auth/oauth/{provider}/login` | The GitHub path is public; no body | `OAuthStartResponse.authorizationUrl` |
| POST | `/api/auth/oauth/{provider}/bind` | Bearer; no body | `OAuthStartResponse.authorizationUrl` |
| GET | `/api/auth/oauth/{provider}/callback` | The GitHub path is public; provider callback | 303 redirect for login; HTML notification page for linking |
| POST | `/api/auth/oauth/complete` | Public; `{ "code": "one-time-exchange-code" }`; retain the browser cookie from the start of the flow | `OAuthCompleteResponse`: `provider`, `intent: "login" / "bind"`, `auth`; only login returns a new local token, while linking returns `auth: null` |
| DELETE | `/api/auth/oauth/{provider}/binding` | Bearer; no body | `OAuthDeleteResponse`: `deleted: true` |
| POST | `/api/auth/oauth/github/setup` | Bearer; `{ "publicBaseUrl": "https://instance.example" }` | `OAuthSetupResponse`: `registrationUrl`, `manifest` |
| GET | `/api/auth/oauth/github/setup/callback` | Public; GitHub App Manifest callback | 303 redirect into the authorization flow on success; HTML notification page on failure |

The owner first logs in with a password, then creates the instance's own GitHub App and links an identity. `publicBaseUrl` is the instance's normal browser URL: remote instances require HTTPS, while local localhost/loopback addresses may use HTTP. The frontend and `/api` share an origin. OAuth tracks the flow in a signed browser session, with a 10-minute lifetime.

The login callback redirects to `/login#oauth_code=...`, or uses `#oauth_error=...` on failure. The linking callback page communicates with the initiating window through origin-checked `postMessage`. The client then calls `/complete` to consume an exchange code tied to the current browser. The code expires after 60 seconds and can be used only once. JWTs are never placed in callback URLs. Configuration and callback responses carry `Cache-Control: no-store`; callbacks also carry `Referrer-Policy: no-referrer`.

## Resume, template, and language data boundaries

`ResumeData` is the resume document body, containing `schemaVersion: 2`, `basic`, and `sections`. Each section has `id`, `kind`, `title`, and `items`; `kind` is one of `education`, `experience`, `project`, `publication`, `achievement`, and `simple_list`. Sections do not store template layout fields.

Each section kind has its own item fields. For example, a project's `techStack` is a string array; `simple_list` has exactly one `{id, content}` item, with visible entries stored as rich text in `content`. Basic information includes `customFields`, whose entries each have `id`, `type`, `label`, and `value`. The [document JSON schema](../backend/app/services/resume_document.schema.json) defines the complete rules.

`ResumeWorkspaceItemResponse` stores `id`, `title`, `updatedAt`, `documentLocale`, `jobBrief`, `typography`, `template`, and `templateSettings` outside the document body. `documentLocale` is `zh` or `en`, independently of the interface language. `template` is a template ID, and `templateSettings` contains visual overrides or `null`. `typography` includes `fontFamily` and `fontSize` in CSS pixels.

A template definition contains `preset`, `name`, `description`, `layout`, `typography`, and `settings`. `preset` must reference a built-in template. Layout, avatar, and decorative image fields belong to `layout`, while visual parameters belong to `settings`. Portable templates omit the server fields `id`, `updatedAt`, and `isBuiltIn`. See [imports.py](../backend/app/schemas/imports.py) and [templates.py](../backend/app/schemas/templates.py) for field and value constraints.

## Workspace pages and preferences

Contracts: [workspace.py schema](../backend/app/schemas/workspace.py) and [workspace routes](../backend/app/routers/workspace.py). Page queries aggregate only the resources needed for initialization. Individual resume documents, Agent sessions, and template editing state are read through their respective resource endpoints.

| Method | Path | Request | `data` |
| --- | --- | --- | --- |
| GET | `/api/workspace/pages/resumes` | None | `ResumesPageResponse`: `resumes`, `customTemplates`, `defaultTemplateIds`, optional `theme` |
| GET | `/api/workspace/pages/resume-editor` | None | `ResumeEditorPageResponse`: `customTemplates`, `defaultTemplateIds`, `modelConfigs`, `agentSettings`, optional `theme` |
| GET | `/api/workspace/pages/templates` | None | `TemplatesPageResponse`: `customTemplates`, `defaultTemplateIds`, optional `theme` |
| GET | `/api/workspace/pages/trash` | None | `TrashPageResponse`: `deletedResumes`, `deletedTemplates`, `customTemplates`, `defaultTemplateIds`, optional `theme` |
| GET | `/api/workspace/pages/models` | None | `ModelsPageResponse`: `modelConfigs`, `agentSettings`, optional `theme` |
| GET | `/api/workspace/pages/settings` | None | `SettingsPageResponse`: `modelConfigs`, `agentSettings`, optional `theme` |
| PUT | `/api/workspace/user-settings` | `{settings: UserSettingsUpdate}`; optional `locale=zh/en` query | `UserSettingsSaveResponse`: saved `locale`, optional `theme`, `agentSettings` |
| PUT | `/api/workspace/default-template` | `{documentLocale, templateId}` | `{defaultTemplateIds: {zh, en}}` |

`theme` is `light`, `dark`, or `system`. Omitting `locale` preserves the existing preference, or uses `en` if none has been set. `defaultTemplateIds` stores separate default template IDs for Chinese and English resumes, rather than a single global template.

See [agent_settings.py](../backend/app/schemas/agent_settings.py) for the exact `agentSettings` structure:

- `defaultModelConfigId`: the default model configuration ID.
- `responseLanguage`: `follow`, `zh`, or `en`.
- `behaviorMode`: `balanced`, `strict`, or `aggressive`.
- `confirmationMode`: `always` or `suggestOnly`.

The Agent reads and fixes these preferences when accepting a run. Changes made during a run affect subsequent runs. Changes to the saved resume still go through the draft review and application endpoint.

## Resumes and versions

Contracts: [resumes.py schema](../backend/app/schemas/resumes.py) and [resumes routes](../backend/app/routers/resumes.py).

| Method | Path | Request | `data` |
| --- | --- | --- | --- |
| GET | `/api/resumes` | `status=active/deleted` query; defaults to `active` | `ResumeListResponse`: `resumes`; deleted items include `deletedAt` |
| POST | `/api/resumes` | `ResumeCreateRequest` | `ResumeDetailResponse` |
| GET | `/api/resumes/{resume_id}` | None | `ResumeDetailResponse` for the current active resume |
| PUT | `/api/resumes/{resume_id}` | `ResumeSaveRequest`; `saveMode=autosave/checkpoint` query, defaults to `checkpoint` | `ResumeDetailResponse` |
| POST | `/api/resumes/{resume_id}/duplicate` | No body | `ResumeDetailResponse` for an independent copy |
| POST | `/api/resumes/{resume_id}/trash` | No body | `{resume: DeletedResumeWorkspaceItemResponse}`; moves the resume to trash |
| POST | `/api/resumes/{resume_id}/restore` | No body | `ResumeDetailResponse` for the restored resume |
| DELETE | `/api/resumes/{resume_id}` | No body; the target must already be in trash | `ResumeDeleteResponse`: `{id}` |
| DELETE | `/api/resumes/trash` | No body | `ResumeTrashEmptyResponse`: `{deletedCount}` |
| GET | `/api/resumes/{resume_id}/versions` | None | `ResumeVersionsResponse`: `versions`, each containing `versionId` and `savedAt` |
| GET | `/api/resumes/{resume_id}/versions/{version_id}` | None | `ResumeDetailResponse` for a historical snapshot |

Minimal creation request:

```json
{"documentLocale":"zh"}
```

The server assigns the resume ID, timestamps, and version, and generates initial content from the selected language and template. `ResumeCreateRequest` can supply a title, document body, template, and typography overrides. Titles are limited to 50 characters.

Saving replaces the complete resource with a request containing `title`, `documentLocale`, `resume`, `jobBrief`, `typography`, `template`, and `templateSettings`. Do not use `ResumeDetailResponse` or server identity fields directly as the request body. `ResumeDetailResponse` is `{resume: ResumeWorkspaceItemResponse, savedAt, versionId}`, where `versionId` is a string.

`autosave` saves the current working content; later saves replace the unpinned autosave version. `checkpoint` pins an explicit history entry. Saving unchanged content does not unconditionally create a new version, and the current autosave can be promoted to a checkpoint. The history list includes only checkpoints. A normal PUT has no `expectedVersionId` query parameter; version concurrency control for applying Agent drafts is described below.

Permanent deletion also removes versions, associated Agent sessions, and attachments. If an Agent turn is still executing, permanent deletion or emptying the trash returns 409 `AGENT_RUN_CONFLICT`. The trash list provides preview data; deleted resumes cannot be edited through the active detail endpoint.

## Custom templates

Contracts: [templates.py schema](../backend/app/schemas/templates.py) and [templates routes](../backend/app/routers/templates.py). These resource endpoints manage custom templates. Built-in templates come from shared presets and cannot be modified through these endpoints.

| Method | Path | Request | `data` |
| --- | --- | --- | --- |
| GET | `/api/templates` | `status=active/deleted` query; defaults to `active` | `TemplateListResponse`: `templates` |
| POST | `/api/templates` | `{template: TemplateArtifactItem}` | `TemplateResponse`: newly created `{template}` |
| GET | `/api/templates/{template_id}` | None | `TemplateEditingResponse`: `{template, checkpoint}` |
| PUT | `/api/templates/{template_id}` | `{template: TemplateArtifactItem, saveMode?: "autosave" / "checkpoint"}` | `TemplateEditingResponse` |
| POST | `/api/templates/{template_id}/discard` | No body | Restored `TemplateEditingResponse` |
| POST | `/api/templates/{template_id}/trash` | No body | `TemplateResponse`; deleted templates include `deletedAt` |
| POST | `/api/templates/{template_id}/restore` | No body | `TemplateResponse` |
| DELETE | `/api/templates/{template_id}` | No body; the target must already be in trash | `TemplateDeleteResponse`: `{id}` |
| DELETE | `/api/templates/trash` | No body | `TemplateTrashEmptyResponse`: `{deletedCount}` |

For template PUT requests, `saveMode` belongs in the JSON body and defaults to `checkpoint`. The first autosave stores the previously explicitly saved content as `checkpoint`; subsequent autosaves retain that same checkpoint. An explicit save confirms the current content and sets `checkpoint` to `null`. `discard` restores that checkpoint, or returns the existing content if no checkpoint is pending. Editing state is stored in the backend and can be recovered when returning to the page. Templates do not have the history version list available for resumes.

The `template` in creation and save requests uses the portable content shape, without `id`, `updatedAt`, `isBuiltIn`, `deletedAt`, or the internal `_checkpoint` field. The newly created ID is the ID used for workspace references.

## Model providers and configurations

Contracts: [model_configs.py schema](../backend/app/schemas/model_configs.py), [model_providers routes](../backend/app/routers/model_providers.py), and [model_configs routes](../backend/app/routers/model_configs.py).

| Method | Path | Request | `data` |
| --- | --- | --- | --- |
| GET | `/api/model-providers` | None | `ModelProvidersResponse`: `providers` manifest |
| POST | `/api/model-providers/discover-models` | `DiscoverModelsRequest` | `DiscoverModelsResponse`: `models`, `source: "cache" / "provider"` |
| POST | `/api/model-providers/context-window` | `{provider, model}`; for local/custom providers | `ModelContextReferenceResponse`: `status`, `contextWindowTokens`, `matchedModel`, `source` |
| GET | `/api/model-configs` | None | `ModelConfigsResponse`: enabled `configs` |
| POST | `/api/model-configs` | `ModelConfigUpsertRequest`; updates an existing configuration if `id` matches, otherwise creates one with a server-assigned ID | `ModelConfigResponse` |
| POST | `/api/model-configs/bulk-delete` | `{ids: string[]}`; nonempty and unique | `ModelConfigBulkDeleteResponse`: `{ids}`; atomic soft deletion, 404 if an ID does not exist |
| DELETE | `/api/model-configs/{client_id}` | No body | `{id}`; disables a single configuration |

`providerKind` is `cloud`, `local`, or `custom`; `apiFamily` is `openai_responses`, `openai_compatible_chat`, `anthropic_messages`, or `google_gemini`. The returned manifest defines provider IDs, default URLs, authentication, and discovery capabilities. Clients should not maintain a separate provider list.

`DiscoverModelsRequest` contains `provider`, `apiUrl`, and optional `apiFamily`, `apiKey`, `configId`, and `refresh`. This endpoint supports only cloud providers with discovery capability:

- The default `refresh: false` reads only the local provider cache. If no cache exists, it returns an empty array with `source: "cache"`.
- `refresh: true` calls the official endpoint declared by the manifest; `apiUrl` does not change the discovery destination. Supply an API key, or use `configId` to select the key from a saved configuration.
- Discovery does not save newly submitted credentials, but does update the model list cache. The response includes context and output limits, image/tool/streaming capabilities, `availableThinkingModes`, and metadata sources.

`context-window` queries only the local model catalog, without contacting the deployed model service. `status` is `found`, `not_found`, or `ambiguous`. The limit may be `null` if there is no unambiguous match; this does not mean zero. The value is a model catalog reference, not a probe of a local deployment's context settings.

The key fields for saving a configuration are provider identity, protocol, `model`, `apiUrl`, `nickname`, credentials, and model parameters. Responses return only `apiKeyPreview`, never the plaintext key. An update may omit `apiKey` to retain saved credentials. The server validates and normalizes capabilities according to the provider mode, rather than trusting client-supplied booleans directly.

`thinkingMode` is only `auto` or `off`. `auto` leaves the model's normal behavior in control. `availableThinkingModes` includes `off` only when both the metadata and the actual protocol support explicitly disabling thinking. Unsupported requests return `MODEL_CONFIG_THINKING_MODE_UNSUPPORTED`. See [thinking.py](../backend/app/services/thinking.py).

`maxTokens: null` uses the runtime's automatic output budget. An explicit value must be a positive safe integer and is checked against the known model output limit. See the schema and [model_configs.py service](../backend/app/services/model_configs.py) for mode-specific constraints on `contextWindowTokens`, sampling parameters, and capability fields. The HTTP configuration contract does not include runtime `timeout_seconds`, decrypted credentials, or raw provider reasoning state.

## Imports, exports, and shared catalogs

### JSON import

Contracts: [imports.py schema](../backend/app/schemas/imports.py) and [import routes](../backend/app/routers/imports.py). Both endpoints accept `multipart/form-data` with a single file field named `file`.

| Method | Path | Content | `data` |
| --- | --- | --- | --- |
| POST | `/api/import/resume` | UTF-8 JSON `ResumeArtifactV1` | `ImportResumeResponse`: `templates`, `resumes` |
| POST | `/api/import/templates` | UTF-8 JSON `TemplateArtifactV1` | `ImportTemplatesResponse`: `templates` |

The `format` is `reseno.resume` for resume files and `reseno.template` for template files; both use a `formatVersion` of `1`. A resume artifact contains `templates` and a nonempty `resumes` array. Embedded custom templates use artifact-local references such as `custom:0`, which must match the resume references. The document body itself still uses `schemaVersion: 2`. A template artifact's `templates` is a nonempty array of portable templates.

Import endpoints only parse and validate; they do not create workspace resources. The client first creates embedded templates and maps their new IDs, then creates the resumes. The frontend serializes JSON exports into the same artifact format. See [import-api.ts](../frontend/src/lib/import-api.ts) and [export-api.ts](../frontend/src/lib/export-api.ts).

The file limit is 10 MiB; the total multipart limit is 10 MiB + 64 KiB, with at most one file and one regular field. Exceeding the file or total multipart byte limit returns 413. Invalid JSON, invalid artifacts, and multipart structure limit violations return 400. See [upload_route.py](../backend/app/routers/upload_route.py) for upload rules.

### PDF and image export

Contracts: [exports.py schema](../backend/app/schemas/exports.py) and [export routes](../backend/app/routers/exports.py).

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| POST | `/api/exports/resume-pdf` | `ExportResumePdfRequest` | JSON `ExportResumePdfResponse` |
| POST | `/api/exports/resume-images` | `ExportResumeImagesRequest` | JSON `ExportResumeImagesResponse` |
| GET | `/api/exports/download/{export_id}` | Optional `fileName` query; Bearer | PDF file |
| GET | `/api/exports/image-download/{export_id}` | Optional `fileName` query; Bearer | Single-page PNG or multi-page ZIP file |

Both generation requests use the same fields:

```json
{
  "resumeId": "server-resume-id",
  "fileNameSeed": "Resume",
  "savedAt": "timestamp-from-save-response",
  "versionId": "version-id-from-save-response"
}
```

`versionId` may be omitted, in which case the current saved version is rendered. The export call does not itself save editor content. Clients should save first, then submit `savedAt` and `versionId` from that save response. The request accepts neither a frontend rendering URL nor a language parameter. The backend reads `documentLocale` from the specified resume snapshot and renders through the `/pdf-export` page under `FRONTEND_RENDER_BASE_URL`.

Generation responses contain `exportId`, `downloadUrl`, `fileName`, and `expiresAt`; image responses also contain `pageCount` and `isArchive`. Files are retained for 1 hour after generation, and downloads do not extend their lifetime. Download URLs still require Bearer authentication, so use authenticated resource requests. Expired or missing files return 404 `EXPORT_FILE_NOT_FOUND`.

The backend reuses Chromium and creates an isolated context for each export. At most four requests may be queued or executing. Full capacity returns 503 `EXPORT_RENDERER_BUSY` with `Retry-After: 1`; shutdown returns `EXPORT_RENDERER_UNAVAILABLE`. PDF/image timeouts return 504 `PDF_RENDER_TIMEOUT` / `IMAGE_RENDER_TIMEOUT`, respectively, and rendering failures return 503 `PDF_RENDER_FAILED` / `IMAGE_RENDER_FAILED`.

### Health and parsing catalogs

| Method | Path | Authentication | Response |
| --- | --- | --- | --- |
| GET | `/health` | No Bearer required | Raw JSON `{ "status": "ok" }` |
| GET | `/api/section-registry` | Bearer | `SectionRegistryResponse`: backend section kinds, default rendering layouts, bilingual labels, and aliases |
| GET | `/api/resume-import-lexicon` | Bearer | `ResumeImportLexiconResponse`: language vocabulary for PDF import |

PDF resume import is performed by the [frontend PDF parser](../frontend/src/lib/pdf-resume-import.ts). It retrieves parsing configuration from the catalog endpoints above, then persists the result through the resume creation endpoint. `/api/import/resume` accepts JSON, not PDF.

## Agent sessions, runs, and review

Contracts: [agent.py schema](../backend/app/schemas/agent.py), [Agent routes](../backend/app/routers/agent.py), and [frontend Agent types](../frontend/src/types/api.ts). All Agent endpoints require Bearer authentication.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| POST | `/api/agent/chat` | `AgentChatRequest` | SSE; `X-Agent-Run-Id` response header |
| GET | `/api/agent/resumes/{resume_id}/session` | None | `AgentSessionResponse` |
| PUT | `/api/agent/resumes/{resume_id}/session` | `AgentSessionReplaceRequest`: `revision`, `messages`, optional `locale` | `AgentSessionResponse` |
| GET | `/api/agent/resumes/{resume_id}/recovery` | None | `AgentSessionRecoveryResponse`: `{session, run}` |
| GET | `/api/agent/runs/{run_id}/events` | Nonnegative integer `after` query, defaults to `0` | SSE; replays events, then continues the subscription |
| DELETE | `/api/agent/runs/{run_id}` | No body | `AgentRunResponse`; requests execution to stop |
| PATCH | `/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft` | `AgentDraftDecisionRequest` | `AgentDraftDecisionResponse`: `{session, resume}` |
| POST | `/api/agent/attachments` | Multipart: `resumeId` and file `file` | `AgentAttachmentResponse` |
| GET | `/api/agent/resumes/{resume_id}/attachments/{attachment_id}` | None | Original attachment file |
| DELETE | `/api/agent/resumes/{resume_id}/attachments/{attachment_id}` | No body; unsent attachments only | `{id}`; 404 if missing or not deletable |

### Accepting user input

`AgentChatRequest.message` is the sole user input for this request. It must have a nonempty `id` without surrounding whitespace, `role: "user"`, and nonempty text or attachments. It cannot carry an assistant `response`. `messages` represents only prior history and must not contain the current message ID again.

Workspace requests that specify `resumeId` must provide the `expectedRevision` read from the session. The backend persists the user message before starting the provider request and rebuilds authoritative history from SQLite. Client-submitted history cannot replace the saved session. Omitting `resumeId` creates a run that is not bound to a persistent session.

`resume` is the `ResumeData` document body; `draftState` represents an unreviewed draft. `modelConfig` accepts only `{id}`, referencing a saved configuration. Chat requests cannot supply API keys, URLs, or parameter overrides. `locale` is the Agent request language; the backend's saved `agentSettings` fixes the final execution preferences. `execution_profile` is internal run data and must not be submitted by clients.

The `stream` field does not switch this HTTP endpoint's response format: an accepted `/chat` request always returns SSE. The frontend wrapper's `AgentChatResponse` is an aggregated result after consuming the full stream, not the endpoint's JSON envelope.

Each resume may have only one active run, with at most four active runs globally. Conflicts return 409 `AGENT_RUN_CONFLICT`; insufficient capacity returns 429 `AGENT_RUN_CAPACITY_EXCEEDED`. The run and model identity are fixed once accepted. Leaving the page or cancelling a fetch or SSE connection does not stop execution. To stop a run, call its DELETE endpoint, then continue reading the stream or recovery response to confirm the final state.

### SSE events and recovery

See [streaming.py](../backend/app/services/agent/runtime/streaming.py) and [agent_runs.py](../backend/app/services/agent_runs.py) for the event protocol, and [agent-stream-client.ts](../frontend/src/lib/agent-stream-client.ts) for the client. Each application event frame has an increasing numeric `id`, an `event` name, and JSON `data`:

```text
id: 2
event: text_delta
data: {"type":"text_delta","delta":"text fragment","timelinePartId":"text-1"}

```

| `event` / `data.type` | Main data | Client handling |
| --- | --- | --- |
| `message_start` | `message` | Create an assistant message |
| `text_delta` | `delta`, `timelinePartId` | Append to the message body and corresponding timeline text |
| `tool_start`, `tool_delta`, `tool_done` | `tool`, `timelinePartId` | Merge public tool state by tool ID and maintain display order |
| `edits` | `message.edits`, `message.transactionState` | Update draft edits and transaction state, without writing to the saved resume |
| `message_delta` | `message` | Receive an absolute message snapshot from compacted replay, rather than appending it as tokens |
| `message_done` | Complete `message` | Receive the final assistant message, including timeline, tools, sources, edits, and draft |
| `error` | `error`, `errorCode` | Display the run error and await a terminal state or perform recovery |
| `run_done` | `runId`, `status`, `executionState`, `errorCode` | Confirm the terminal execution state |

When there are no application events, a `: ping` comment heartbeat is sent approximately every 12 seconds. Heartbeats have no event ID. Responses carry `Cache-Control: no-cache` and `X-Accel-Buffering: no`; proxies should forward and promptly flush events.

To reconnect, pass the last consumed event ID as `?after=`; sending only the `Last-Event-ID` header is insufficient. The replay buffer may fold early deltas into complete `message_delta`/`message_done` snapshots, so clients must support snapshot merging and deduplication by ID. `message_done` cannot replace `run_done` as a signal of run success: a failed run may still have a displayable final message while retaining a failed execution state.

A run's `status` is `active`, `completed`, `cancelled`, or `failed`; a persistent turn's `executionState` is `running`, `succeeded`, `cancelled`, or `failed`. Terminal error types are `AGENT_PROVIDER_AUTH_ERROR`, `AGENT_PROVIDER_ERROR`, `AGENT_PROVIDER_TIMEOUT`, `AGENT_INTERNAL_ERROR`, `AGENT_RUN_CANCELLED`, and `AGENT_EDIT_TRANSACTION_INCOMPLETE`.

`AgentSessionResponse` contains `resumeId`, `revision`, `messages`, and `executions`. `executions` stores run/turn IDs, model identity snapshots, start and end times, and execution results. `recovery` returns the authoritative session and its matching active run within the same recovery flow, or `run: null` if no run is active. Runs and SSE replay belong to the current backend process; old executions cannot be reconnected after a restart. On startup, the backend marks interrupted persistent executions as failed. History remains available through the session endpoint.

Session PUT uses optimistic concurrency control through `revision`. It replaces the application's conversation history and cleans up corresponding execution records and attachments that are no longer referenced. Replacement is not allowed during an active run. A stale revision returns 409 `AGENT_SESSION_REVISION_CONFLICT`; duplicate turns or conflicting message identities return `AGENT_SESSION_TURN_CONFLICT`. After these errors, read recovery/session and reconcile the interface with server state rather than overwriting blindly.

### Draft review and application

An assistant message's `transactionState` is `none`, `provisional`, `committed`, or `rolled_back`. Only a completed draft transaction can enter review. Provisional edits in the stream do not mean that changes have been saved to the resume. The [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) defines edit operation fields and allowed paths.

`draft.baseResume` stores the draft's base document. `draft.reviewItems` divides ordered edits into independently reviewable groups, each with `id`, `editIds`, and `status`. Edit IDs must be covered exactly once and remain in order. Review item status is `pending`, `applied`, `discarded`, or `superseded`; client review commands may submit only `applied` or `discarded`.

Example request to discard selected review items:

```json
{
  "revision": "current-session-revision",
  "status": "discarded",
  "reviewItemIds": ["pending-review-item-id"]
}
```

To apply edits, use `status: "applied"` and also submit `expectedVersionId` and `resume`. `resume` must be the complete merged candidate conforming to the document schema. The frontend produces a reviewable result from the draft and current editor content, then invokes this command after user confirmation.

On application, `revision` and `expectedVersionId` jointly prevent overwriting newer session decisions or saved resume content. The backend writes the resume autosave and review state in one transaction. The response's `resume` is the saved `ResumeDetailResponse`. A discard request submits only `revision`, `status: "discarded"`, and nonempty `reviewItemIds`. It must not include `resume` or `expectedVersionId`, and the response has `resume: null`.

Review item IDs must be unique and refer to pending items. Conflicts use HTTP 409: `AGENT_SESSION_REVISION_CONFLICT` (may include a new `revision`), `RESUME_VERSION_CONFLICT` (includes `versionId`), `AGENT_RUN_CONFLICT` (may include `runId`), and `AGENT_DRAFT_DECISION_CONFLICT` (may include `revision` and `status`). These additional fields are in the envelope's `data`.

### Attachments

Upload attachments first, then reference the returned backend attachment IDs and metadata in the user message's `files`. The upload response contains `id`, `filename`, `mediaType`, and `kind: "text" / "image"`. Do not use temporary browser URLs as persistent references. Attachments belong to the specified resume's Agent session and cannot be reused across resumes.

Supported attachments include text, PDF, DOCX, and images recognized by their contents. Each attachment is limited to 10 MiB. Provider context accepts at most five attachments totaling at most 20 MiB. Extracted text is limited to 250,000 characters per file and 400,000 characters per request; PDFs are limited to 50 pages. See [attachments.py](../backend/app/services/agent/attachments.py) for exact format detection and limits. These provider request limits do not truncate saved history references.

Before sending, DELETE can cancel an upload. Attachments already referenced in sent messages cannot be deleted through this endpoint. Unsent attachments become eligible for background cleanup after 24 hours. Sent attachments are managed with the lifetime of their history references and parent resume. Downloads return the original file and require Bearer authentication.
