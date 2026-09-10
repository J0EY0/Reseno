# Reseno API

[English](API.md) | 简体中文

本文描述前端与 FastAPI 后端之间的 HTTP 接口。默认基址为同源 `/api`；开发环境由 Vite 代理到后端。前端可用 `VITE_API_BASE_URL` 指定 API 基址，开发代理目标可用 `VITE_DEV_API_TARGET` 指定。启动、密钥和存储配置见 [README](../README_ZH.md)。

## 契约来源

下文表格中的响应类型均指 JSON envelope 的 `data`，标明 SSE、文件、HTML 或重定向的接口除外。JSON 字段使用 schema 声明的别名，例如 `documentLocale`、`savedAt`。

| 内容 | 精确字段与实现 |
| --- | --- |
| HTTP 路由、查询参数、状态码 | [backend/app/routers](../backend/app/routers) |
| 请求与响应校验 | [backend/app/schemas](../backend/app/schemas) |
| 前端 API 类型 | [frontend/src/types/api.ts](../frontend/src/types/api.ts) |
| 简历文档结构 | [resume_document.schema.json](../backend/app/services/resume_document.schema.json) |
| Agent 编辑操作 | [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) |
| 前端简历、模板和工作区类型 | [frontend/src/types/resume.ts](../frontend/src/types/resume.ts) |
| 内置模板定义 | [template_presets.json](../backend/app/services/template_presets.json) |

服务通过 `app.main:create_app` 创建。`/docs`、`/redoc` 和 `/openapi.json` 未公开；契约工具可对应用对象调用 `app.openapi()`。SSE、手工文件响应及认证中间件规则还需参照对应实现。

## HTTP 与认证约定

普通 JSON 成功响应为：

```json
{
  "code": 0,
  "message": "OK",
  "data": {},
  "requestId": null
}
```

`requestId` 可以为空或省略。`message` 是稳定的消息标识，由客户端本地化。错误保留实际 HTTP 状态，不通过 HTTP 200 表示失败。

| HTTP 状态 | 含义 | 常见 `code` |
| --- | --- | --- |
| 2xx | 成功 | `0` |
| 400、403、409、413、429 | 无效请求、禁止操作、冲突、上传过大、运行容量不足 | `40000` |
| 401 | 登录失败或会话无效 | `40001` |
| 404 | 资源不存在 | `40004` |
| 422 | 请求结构或字段校验失败 | 请求模型校验为 `40002` |
| 5xx | 服务端或上游错误 | `50000` |

Pydantic 请求校验失败返回 `message: "VALIDATION_ERROR"`，`data.errors` 包含字段错误。手工抛出的 HTTP 错误按 HTTP 状态映射；例如 Agent 会话替换校验失败使用 HTTP 422、`code: 40000`、`message: "AGENT_SESSION_REPLACEMENT_INVALID"`。完整规则见 [exceptions.py](../backend/app/exceptions.py)。

受保护接口要求：

```http
Authorization: Bearer <accessToken>
```

[认证中间件](../backend/app/middleware/auth.py) 仅对下列实际 API 路径免除 Bearer 校验：

- `/api/auth/setup`
- `/api/auth/login`
- `/api/auth/oauth/github/login`
- `/api/auth/oauth/github/callback`
- `/api/auth/oauth/github/setup/callback`
- `/api/auth/oauth/complete`

`OPTIONS` 请求也不经过 Bearer 校验。GitHub 回调和兑换仍校验 OAuth 流程状态及浏览器会话，公开不等于无校验。`/health` 位于 API 前缀之外。

认证中间件拒绝请求时返回 HTTP 401、`WWW-Authenticate: Bearer`，以及：

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

`reason` 为 `missing_token`、`invalid_or_expired_token` 或 `owner_missing_or_changed`。密码错误则使用 `INVALID_CREDENTIALS`。客户端应按状态码和消息标识处理，不依赖英文错误句子。

JSON envelope 不适用于 Agent SSE、附件和导出文件下载、OAuth HTML/303 回调、`/health`。`/api/*` 接口交给通用异常处理器的错误使用 JSON 错误 envelope；OAuth 流程失败沿对应回调格式返回，SSE 已建立后的运行错误通过流事件报告。

## Owner 与登录会话

契约：[auth.py schema](../backend/app/schemas/auth.py)、[auth 路由](../backend/app/routers/auth.py)、[auth_tokens.py](../backend/app/services/auth_tokens.py)。实例只有一个 owner，没有公开注册或默认密码。

| 方法 | 路径 | 请求 | 响应与行为 |
| --- | --- | --- | --- |
| GET | `/api/auth/setup` | 无；公开 | `AuthSetupStatusResponse`：`setupRequired`、`githubLoginAvailable`；`Cache-Control: no-store` |
| POST | `/api/auth/setup` | `AuthSetupRequest`：`username`、`password`、`confirmPassword`；公开 | 从 loopback 客户端创建唯一 owner，返回 `AuthLoginResponse`；非本机 403，已初始化 409 |
| POST | `/api/auth/login` | `AuthLoginRequest`：`username`、`password`；公开 | `AuthLoginResponse`；凭据错误 401 |
| POST | `/api/auth/refresh` | 有效 Bearer；无请求体 | `AuthLoginResponse`；续签并撤销旧 token |
| POST | `/api/auth/username` | `AuthUsernameUpdateRequest`：`newUsername`、`currentPassword`；有效 Bearer | `AuthLoginResponse`；验证当前密码后修改用户名；用户名或密码无效 400，会话失效或 owner 已变化 401 |
| POST | `/api/auth/password` | `AuthPasswordUpdateRequest`：`currentPassword`、`newPassword`、`confirmPassword` | `AuthPasswordUpdateResponse`：`username`、`updated: true`；原密码错误 400 |

用户名去除首尾空白后至少 3 个字符，只允许 ASCII 字母、数字、`_`、`-`。新密码至少 8 个字符，包含 ASCII 字母和数字，并与确认值一致。首次设置判断的是后端收到的客户端地址。

`AuthLoginResponse` 包含 `username`、`accessToken`、`expiresAt`、`tokenType: "bearer"`。JWT 有效期为签发起 36 小时；续签要求旧 token 仍有效。旧 token 的 `jwt_id` 与原到期时间写入 `auth.db` 的 `auth_revoked_tokens`，撤销在后端重启后仍有效，同一 token 只能成功续签一次。

用户名修改在同一事务中核对当前 owner 与请求的认证 revision、验证当前密码，并更新用户名和认证 revision；替换凭证签发成功后才提交。实际改名会使全部已有 JWT 失效，客户端使用响应中的新凭证继续登录；改回曾用名也不会恢复旧 JWT。去除首尾空白后与当前用户名相同的请求仍验证会话和密码，但不更新 owner 或认证 revision，并返回新的有效凭证。改名保留当前密码、GitHub 身份绑定和简历数据；之后使用新用户名和原密码登录。

密码修改会更新 owner 的认证 revision，使全部已有 JWT 失效。前端将会话存入同源 localStorage，并协调标签页之间的续签、登录和退出；客户端退出清理本地会话，没有单独的服务端 logout 接口。会话客户端见 [auth.ts](../frontend/src/lib/auth.ts)、[auth-session.ts](../frontend/src/lib/auth-session.ts)。

### GitHub App 与身份绑定

契约：[auth_oauth.py](../backend/app/routers/auth_oauth.py)、[auth.py schema](../backend/app/schemas/auth.py)。`provider` 当前只接受 `github`。

| 方法 | 路径 | 请求与认证 | 响应 |
| --- | --- | --- | --- |
| GET | `/api/auth/oauth/identities` | Bearer | `OAuthIdentitiesResponse`：已绑定身份 `identities` 与 provider 配置状态 `providers` |
| POST | `/api/auth/oauth/{provider}/login` | GitHub 路径公开；无请求体 | `OAuthStartResponse.authorizationUrl` |
| POST | `/api/auth/oauth/{provider}/bind` | Bearer；无请求体 | `OAuthStartResponse.authorizationUrl` |
| GET | `/api/auth/oauth/{provider}/callback` | GitHub 路径公开；供 provider 回调 | 登录为 303 重定向；绑定为 HTML 通知页 |
| POST | `/api/auth/oauth/complete` | 公开；`{ "code": "一次性交换码" }`；保留发起流程的浏览器 cookie | `OAuthCompleteResponse`：`provider`、`intent: "login" / "bind"`、`auth`；仅登录返回新本地 token，绑定时 `auth: null` |
| DELETE | `/api/auth/oauth/{provider}/binding` | Bearer；无请求体 | `OAuthDeleteResponse`：`deleted: true` |
| POST | `/api/auth/oauth/github/setup` | Bearer；`{ "publicBaseUrl": "https://实例地址" }` | `OAuthSetupResponse`：`registrationUrl`、`manifest` |
| GET | `/api/auth/oauth/github/setup/callback` | 公开；供 GitHub App Manifest 回调 | 成功 303 进入授权流程；失败 HTML 通知页 |

owner 先使用密码登录，再创建实例自己的 GitHub App 并绑定身份。`publicBaseUrl` 使用实例正常浏览器地址：远端要求 HTTPS，本机 localhost/loopback 可用 HTTP。前端与 `/api` 使用同源地址；OAuth 使用签名浏览器会话记录流程，流程有效期 10 分钟。

登录回调跳转至 `/login#oauth_code=...`，失败使用 `#oauth_error=...`。绑定回调页面通过带来源校验的 `postMessage` 与发起窗口交接。客户端再调用 `/complete` 消费与当前浏览器关联的交换码；交换码有效期 60 秒且只能使用一次。JWT 不放入回调 URL。配置和回调响应带 `Cache-Control: no-store`；回调带 `Referrer-Policy: no-referrer`。

## 简历、模板与语言的数据边界

`ResumeData` 是简历正文，结构为 `schemaVersion: 2`、`basic`、`sections`。每个 section 有 `id`、`kind`、`title`、`items`；`kind` 是 `education`、`experience`、`project`、`publication`、`achievement`、`simple_list`。section 不存放模板布局字段。

每种 section 的 item 使用自己的字段。例如 project 的 `techStack` 是字符串数组；`simple_list` 恰有一个 `{id, content}` item，可见条目保存在 `content` 的富文本中。基本信息包含 `customFields`，每项有 `id`、`type`、`label`、`value`。完整规则以 [文档 JSON schema](../backend/app/services/resume_document.schema.json) 为准。

`ResumeWorkspaceItemResponse` 在正文外保存 `id`、`title`、`updatedAt`、`documentLocale`、`jobBrief`、`typography`、`template`、`templateSettings`。`documentLocale` 为 `zh` 或 `en`，独立于界面语言；`template` 是模板 ID，`templateSettings` 为视觉覆盖或 `null`。`typography` 包含 `fontFamily` 与 CSS 像素单位的 `fontSize`。

模板定义包含 `preset`、`name`、`description`、`layout`、`typography`、`settings`。`preset` 必须引用内置模板；布局、头像与装饰图片字段在 `layout` 中，视觉参数在 `settings` 中。便携模板不含服务端的 `id`、`updatedAt`、`isBuiltIn`。字段与数值约束见 [imports.py](../backend/app/schemas/imports.py)、[templates.py](../backend/app/schemas/templates.py)。

## 工作区页面与偏好

契约：[workspace.py schema](../backend/app/schemas/workspace.py)、[workspace 路由](../backend/app/routers/workspace.py)。页面查询仅聚合初始化所需资源；单份简历正文、Agent 会话和模板编辑状态通过各自资源接口读取。

| 方法 | 路径 | 请求 | `data` |
| --- | --- | --- | --- |
| GET | `/api/workspace/pages/resumes` | 无 | `ResumesPageResponse`：`resumes`、`customTemplates`、`defaultTemplateIds`、可选 `theme` |
| GET | `/api/workspace/pages/resume-editor` | 无 | `ResumeEditorPageResponse`：`customTemplates`、`defaultTemplateIds`、`modelConfigs`、`agentSettings`、可选 `theme` |
| GET | `/api/workspace/pages/templates` | 无 | `TemplatesPageResponse`：`customTemplates`、`defaultTemplateIds`、可选 `theme` |
| GET | `/api/workspace/pages/trash` | 无 | `TrashPageResponse`：`deletedResumes`、`deletedTemplates`、`customTemplates`、`defaultTemplateIds`、可选 `theme` |
| GET | `/api/workspace/pages/models` | 无 | `ModelsPageResponse`：`modelConfigs`、`agentSettings`、可选 `theme` |
| GET | `/api/workspace/pages/settings` | 无 | `SettingsPageResponse`：`modelConfigs`、`agentSettings`、可选 `theme` |
| PUT | `/api/workspace/user-settings` | `{settings: UserSettingsUpdate}`；可选查询 `locale=zh/en` | `UserSettingsSaveResponse`：保存后的 `locale`、可选 `theme`、`agentSettings` |
| PUT | `/api/workspace/default-template` | `{documentLocale, templateId}` | `{defaultTemplateIds: {zh, en}}` |

`theme` 为 `light`、`dark`、`system`。省略 `locale` 会保留既有偏好，首次未设置时为 `en`。`defaultTemplateIds` 为中文、英文简历分别保存默认模板 ID，不是单一全局模板。

`agentSettings` 的准确结构见 [agent_settings.py](../backend/app/schemas/agent_settings.py)：

- `defaultModelConfigId`：默认模型配置 ID。
- `responseLanguage`：`follow`、`zh`、`en`。
- `behaviorMode`：`balanced`、`strict`、`aggressive`。
- `confirmationMode`：`always`、`suggestOnly`。

Agent 在接受一次运行时读取并固定这些偏好，运行期间修改设置作用于之后的运行。正式简历仍通过审核应用接口提交。

## 简历与版本

契约：[resumes.py schema](../backend/app/schemas/resumes.py)、[resumes 路由](../backend/app/routers/resumes.py)。

| 方法 | 路径 | 请求 | `data` |
| --- | --- | --- | --- |
| GET | `/api/resumes` | 查询 `status=active/deleted`，默认 `active` | `ResumeListResponse`：`resumes`；已删除项附带 `deletedAt` |
| POST | `/api/resumes` | `ResumeCreateRequest` | `ResumeDetailResponse` |
| GET | `/api/resumes/{resume_id}` | 无 | 当前活动简历的 `ResumeDetailResponse` |
| PUT | `/api/resumes/{resume_id}` | `ResumeSaveRequest`；查询 `saveMode=autosave/checkpoint`，默认 `checkpoint` | `ResumeDetailResponse` |
| POST | `/api/resumes/{resume_id}/duplicate` | 无请求体 | 独立副本的 `ResumeDetailResponse` |
| POST | `/api/resumes/{resume_id}/trash` | 无请求体 | `{resume: DeletedResumeWorkspaceItemResponse}`；移入回收站 |
| POST | `/api/resumes/{resume_id}/restore` | 无请求体 | 恢复后的 `ResumeDetailResponse` |
| DELETE | `/api/resumes/{resume_id}` | 无请求体；目标须已在回收站 | `ResumeDeleteResponse`：`{id}` |
| DELETE | `/api/resumes/trash` | 无请求体 | `ResumeTrashEmptyResponse`：`{deletedCount}` |
| GET | `/api/resumes/{resume_id}/versions` | 无 | `ResumeVersionsResponse`：`versions`，每项含 `versionId`、`savedAt` |
| GET | `/api/resumes/{resume_id}/versions/{version_id}` | 无 | 历史快照的 `ResumeDetailResponse` |

创建最小请求：

```json
{"documentLocale":"zh"}
```

服务端分配简历 ID、时间与版本，按所选语言和模板生成起始内容。可以通过 `ResumeCreateRequest` 提供标题、正文、模板及排版覆盖。标题最长 50 个字符。

保存是整份替换请求，包含 `title`、`documentLocale`、`resume`、`jobBrief`、`typography`、`template`、`templateSettings`；不要把 `ResumeDetailResponse` 或服务端身份字段直接当请求体。`ResumeDetailResponse` 为 `{resume: ResumeWorkspaceItemResponse, savedAt, versionId}`，`versionId` 是字符串。

`autosave` 保存当前工作内容，后续保存会替换未固定的自动保存版本；`checkpoint` 固定显式历史节点。同内容保存不会无条件创建新版本，当前 autosave 可被提升为 checkpoint。历史列表只列 checkpoint。普通 PUT 没有 `expectedVersionId` 查询参数；Agent 审核应用的版本并发控制见后文。

彻底删除同时清理版本、关联 Agent 会话与附件。有仍在执行的 Agent turn 时，彻底删除或清空回收站返回 409 `AGENT_RUN_CONFLICT`。回收站列表提供预览数据，不能通过活动详情接口编辑已删除简历。

## 自定义模板

契约：[templates.py schema](../backend/app/schemas/templates.py)、[templates 路由](../backend/app/routers/templates.py)。这些资源接口管理自定义模板；内置模板由共享预设提供，不通过这些接口修改。

| 方法 | 路径 | 请求 | `data` |
| --- | --- | --- | --- |
| GET | `/api/templates` | 查询 `status=active/deleted`，默认 `active` | `TemplateListResponse`：`templates` |
| POST | `/api/templates` | `{template: TemplateArtifactItem}` | `TemplateResponse`：新建 `{template}` |
| GET | `/api/templates/{template_id}` | 无 | `TemplateEditingResponse`：`{template, checkpoint}` |
| PUT | `/api/templates/{template_id}` | `{template: TemplateArtifactItem, saveMode?: "autosave" / "checkpoint"}` | `TemplateEditingResponse` |
| POST | `/api/templates/{template_id}/discard` | 无请求体 | 恢复后的 `TemplateEditingResponse` |
| POST | `/api/templates/{template_id}/trash` | 无请求体 | `TemplateResponse`；已删除模板附带 `deletedAt` |
| POST | `/api/templates/{template_id}/restore` | 无请求体 | `TemplateResponse` |
| DELETE | `/api/templates/{template_id}` | 无请求体；目标须已在回收站 | `TemplateDeleteResponse`：`{id}` |
| DELETE | `/api/templates/trash` | 无请求体 | `TemplateTrashEmptyResponse`：`{deletedCount}` |

模板 PUT 的 `saveMode` 在 JSON 请求体中，默认 `checkpoint`。首次 autosave 保存此前显式内容为 `checkpoint`，后续 autosave 保留同一个 checkpoint；显式保存确认当前内容并使 `checkpoint` 为 `null`。`discard` 恢复该 checkpoint，没有待处理 checkpoint 时返回现有内容。编辑状态保存在后端，重新进入页面仍可恢复；模板没有简历式的历史版本列表。

创建和保存请求中的 `template` 使用便携内容形状，不携带 `id`、`updatedAt`、`isBuiltIn`、`deletedAt` 或内部 `_checkpoint` 字段。创建得到的新 ID 才是工作区引用 ID。

## 模型提供商与配置

契约：[model_configs.py schema](../backend/app/schemas/model_configs.py)、[model_providers 路由](../backend/app/routers/model_providers.py)、[model_configs 路由](../backend/app/routers/model_configs.py)。

| 方法 | 路径 | 请求 | `data` |
| --- | --- | --- | --- |
| GET | `/api/model-providers` | 无 | `ModelProvidersResponse`：`providers` manifest |
| POST | `/api/model-providers/discover-models` | `DiscoverModelsRequest` | `DiscoverModelsResponse`：`models`、`source: "cache" / "provider"` |
| POST | `/api/model-providers/context-window` | `{provider, model}`；用于 local/custom provider | `ModelContextReferenceResponse`：`status`、`contextWindowTokens`、`matchedModel`、`source` |
| GET | `/api/model-configs` | 无 | `ModelConfigsResponse`：启用的 `configs` |
| POST | `/api/model-configs` | `ModelConfigUpsertRequest`；`id` 命中已有配置则更新，否则由服务端分配新 ID 创建 | `ModelConfigResponse` |
| POST | `/api/model-configs/bulk-delete` | `{ids: string[]}`；非空、无重复 | `ModelConfigBulkDeleteResponse`：`{ids}`；原子软删除，ID 不存在返回 404 |
| DELETE | `/api/model-configs/{client_id}` | 无请求体 | `{id}`；停用单个配置 |

`providerKind` 为 `cloud`、`local`、`custom`；`apiFamily` 为 `openai_responses`、`openai_compatible_chat`、`anthropic_messages`、`google_gemini`。provider ID、默认地址、鉴权及发现能力以 manifest 返回值为准，客户端不要另维护 provider 清单。

`DiscoverModelsRequest` 包含 `provider`、`apiUrl`，以及可选 `apiFamily`、`apiKey`、`configId`、`refresh`。此端点只支持具有发现能力的 cloud provider：

- 默认 `refresh: false` 只读本地 provider 缓存，没有缓存时返回空数组和 `source: "cache"`。
- `refresh: true` 调用 manifest 声明的官方端点；`apiUrl` 不用于改变发现目标。可提交 API key，或通过 `configId` 使用已保存配置的 key。
- 发现不会保存新提交的凭据，但会更新模型列表缓存。响应包含上下文、输出上限、图像/工具/流式能力、`availableThinkingModes` 与元数据来源。

`context-window` 只查询本地模型目录，不联系部署模型服务。`status` 是 `found`、`not_found`、`ambiguous`；未获得明确匹配时上限可为 `null`，不能解释为零。这个值是模型目录参考，不是对本地部署上下文设置的探测。

保存配置的关键字段为 provider 身份、协议、`model`、`apiUrl`、`nickname`、凭据及模型参数。响应只返回 `apiKeyPreview`，不返回明文 key；更新时可省略 `apiKey` 保留已保存凭据。服务端按 provider 模式校验并规范化能力，而非直接信任客户端布尔值。

`thinkingMode` 仅为 `auto` 或 `off`。`auto` 委托模型正常行为；只有元数据与实际协议都支持显式关闭时，`availableThinkingModes` 才包含 `off`，不支持的请求返回 `MODEL_CONFIG_THINKING_MODE_UNSUPPORTED`。见 [thinking.py](../backend/app/services/thinking.py)。

`maxTokens: null` 使用运行时自动输出预算；显式值须为正安全整数，并接受已知模型输出上限校验。`contextWindowTokens`、采样参数及 capability 字段的模式约束见 schema 与 [model_configs.py service](../backend/app/services/model_configs.py)。HTTP 配置契约不包含运行时 `timeout_seconds`、解密后的凭据或 provider 原始推理状态。

## 导入、导出与共享目录

### JSON 导入

契约：[imports.py schema](../backend/app/schemas/imports.py)、[imports 路由](../backend/app/routers/imports.py)。两个端点均接收 `multipart/form-data`，单个文件字段名为 `file`。

| 方法 | 路径 | 内容 | `data` |
| --- | --- | --- | --- |
| POST | `/api/import/resume` | UTF-8 JSON `ResumeArtifactV1` | `ImportResumeResponse`：`templates`、`resumes` |
| POST | `/api/import/templates` | UTF-8 JSON `TemplateArtifactV1` | `ImportTemplatesResponse`：`templates` |

简历文件的 `format` 为 `reseno.resume`，模板文件为 `reseno.template`，两者 `formatVersion` 均为 `1`。简历 artifact 含 `templates` 与非空 `resumes`；内嵌自定义模板用 `custom:0` 等 artifact 局部引用，必须与简历引用对应。正文自身仍使用 `schemaVersion: 2`。模板 artifact 的 `templates` 为非空便携模板数组。

导入端点只解析与校验，不创建工作区资源。客户端先创建内嵌模板并映射新 ID，再创建简历。JSON 导出由前端序列化为同一 artifact 格式，见 [import-api.ts](../frontend/src/lib/import-api.ts)、[export-api.ts](../frontend/src/lib/export-api.ts)。

单文件上限 10 MiB；multipart 总体上限为 10 MiB + 64 KiB，最多一个文件和一个普通字段。文件或 multipart 总字节超限使用 413；无效 JSON、artifact 及 multipart 结构限制错误使用 400。上传规则见 [upload_route.py](../backend/app/routers/upload_route.py)。

### PDF 与图片导出

契约：[exports.py schema](../backend/app/schemas/exports.py)、[exports 路由](../backend/app/routers/exports.py)。

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/api/exports/resume-pdf` | `ExportResumePdfRequest` | JSON `ExportResumePdfResponse` |
| POST | `/api/exports/resume-images` | `ExportResumeImagesRequest` | JSON `ExportResumeImagesResponse` |
| GET | `/api/exports/download/{export_id}` | 可选查询 `fileName`；Bearer | PDF 文件 |
| GET | `/api/exports/image-download/{export_id}` | 可选查询 `fileName`；Bearer | 单页 PNG 或多页 ZIP 文件 |

两个生成请求使用相同字段：

```json
{
  "resumeId": "服务端简历ID",
  "fileNameSeed": "Resume",
  "savedAt": "保存响应中的时间",
  "versionId": "保存响应中的版本ID"
}
```

`versionId` 可省略，此时渲染当前保存版本。导出调用本身不保存编辑器内容，客户端应先保存，再提交该次响应的 `savedAt` 与 `versionId`。请求不接受前端渲染 URL 或语言参数；后端从指定简历快照读取 `documentLocale`，通过 `FRONTEND_RENDER_BASE_URL` 对应的 `/pdf-export` 页面完成渲染。

生成响应包含 `exportId`、`downloadUrl`、`fileName`、`expiresAt`；图片另含 `pageCount`、`isArchive`。文件自生成起保留 1 小时，下载不续期；下载 URL 仍要求 Bearer，请使用带鉴权的资源请求。过期或缺失返回 404 `EXPORT_FILE_NOT_FOUND`。

后端复用 Chromium，每次导出创建独立 context；最多四个请求排队或执行。容量满为 503 `EXPORT_RENDERER_BUSY`，带 `Retry-After: 1`；关闭中为 `EXPORT_RENDERER_UNAVAILABLE`。PDF/图片超时分别为 504 `PDF_RENDER_TIMEOUT` / `IMAGE_RENDER_TIMEOUT`，渲染失败为 503 `PDF_RENDER_FAILED` / `IMAGE_RENDER_FAILED`。

### 健康与解析目录

| 方法 | 路径 | 认证 | 响应 |
| --- | --- | --- | --- |
| GET | `/health` | 不要求 Bearer | 原始 JSON `{ "status": "ok" }` |
| GET | `/api/section-registry` | Bearer | `SectionRegistryResponse`：后端 section kind、默认渲染布局、双语标签与别名 |
| GET | `/api/resume-import-lexicon` | Bearer | `ResumeImportLexiconResponse`：PDF 导入所需语言词汇 |

PDF 简历导入由[前端 PDF 解析器](../frontend/src/lib/pdf-resume-import.ts)执行，使用上述目录接口取得解析配置，再调用简历创建接口持久化。`/api/import/resume` 接受 JSON，不接收 PDF。

## Agent 会话、运行与审核

契约：[agent.py schema](../backend/app/schemas/agent.py)、[agent 路由](../backend/app/routers/agent.py)、[前端 Agent 类型](../frontend/src/types/api.ts)。所有 Agent 接口都需要 Bearer。

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/api/agent/chat` | `AgentChatRequest` | SSE；响应头 `X-Agent-Run-Id` |
| GET | `/api/agent/resumes/{resume_id}/session` | 无 | `AgentSessionResponse` |
| PUT | `/api/agent/resumes/{resume_id}/session` | `AgentSessionReplaceRequest`：`revision`、`messages`、可选 `locale` | `AgentSessionResponse` |
| GET | `/api/agent/resumes/{resume_id}/recovery` | 无 | `AgentSessionRecoveryResponse`：`{session, run}` |
| GET | `/api/agent/runs/{run_id}/events` | 查询 `after` 为非负整数，默认 `0` | SSE；重放后继续订阅 |
| DELETE | `/api/agent/runs/{run_id}` | 无请求体 | `AgentRunResponse`；请求停止执行 |
| PATCH | `/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft` | `AgentDraftDecisionRequest` | `AgentDraftDecisionResponse`：`{session, resume}` |
| POST | `/api/agent/attachments` | multipart：`resumeId` 与文件 `file` | `AgentAttachmentResponse` |
| GET | `/api/agent/resumes/{resume_id}/attachments/{attachment_id}` | 无 | 原始附件文件 |
| DELETE | `/api/agent/resumes/{resume_id}/attachments/{attachment_id}` | 无请求体；仅未发送附件 | `{id}`；不存在或不可删除为 404 |

### 接受一次用户输入

`AgentChatRequest.message` 是本次唯一用户输入，必须有非空且无首尾空白的 `id`、`role: "user"`，以及非空文本或附件，不能携带 assistant `response`。`messages` 只表示此前历史，不能再次包含本次 message ID。

工作区请求指定 `resumeId` 时必须提供从会话读取的 `expectedRevision`。后端在开始 provider 请求之前持久化用户消息，并从 SQLite 重建权威历史；客户端提交的历史不能替换已保存会话。`resumeId` 省略时使用不绑定持久会话的运行。

`resume` 是 `ResumeData` 正文；`draftState` 表示未审核草稿。`modelConfig` 只接受 `{id}`，引用已保存配置，不能在 chat 中传 API key、地址或参数覆盖。`locale` 为 Agent 请求语言；最终执行偏好由后端保存的 `agentSettings` 固定。`execution_profile` 属于内部运行数据，客户端不提交。

`stream` 字段不切换本 HTTP 端点的响应格式：成功接受的 `/chat` 始终返回 SSE。前端封装的 `AgentChatResponse` 是消费完整流后的聚合结果，不是该端点的 JSON envelope。

每份简历同时只能有一个活动 run，全局最多四个活动 run；冲突返回 409 `AGENT_RUN_CONFLICT`，容量不足返回 429 `AGENT_RUN_CAPACITY_EXCEEDED`。run 与模型身份在接受后固定。断开页面、取消 fetch 或 SSE 连接不等于停止运行；停止必须调用 run DELETE，之后继续读取流或 recovery 确认最终状态。

### SSE 事件与恢复

事件协议的实现见 [streaming.py](../backend/app/services/agent/runtime/streaming.py)、[agent_runs.py](../backend/app/services/agent_runs.py)，客户端见 [agent-stream-client.ts](../frontend/src/lib/agent-stream-client.ts)。每个业务帧具有递增数字 `id`、`event` 名称和 JSON `data`：

```text
id: 2
event: text_delta
data: {"type":"text_delta","delta":"正文片段","timelinePartId":"text-1"}

```

| `event` / `data.type` | 主要数据 | 客户端处理 |
| --- | --- | --- |
| `message_start` | `message` | 建立 assistant 消息 |
| `text_delta` | `delta`、`timelinePartId` | 追加正文与对应 timeline 文本 |
| `tool_start`、`tool_delta`、`tool_done` | `tool`、`timelinePartId` | 按 tool ID 合并公开工具状态，维护显示顺序 |
| `edits` | `message.edits`、`message.transactionState` | 更新草稿编辑及事务状态，不写正式简历 |
| `message_delta` | `message` | 接收压缩重放后的绝对消息快照，不当作追加 token |
| `message_done` | 完整 `message` | 接收最终 assistant 消息，含 timeline、tools、sources、edits、draft |
| `error` | `error`、`errorCode` | 显示运行错误，等待终态或执行恢复 |
| `run_done` | `runId`、`status`、`executionState`、`errorCode` | 确认执行终态 |

无业务事件时约每 12 秒发送 `: ping` 注释心跳，心跳没有事件 ID。响应带 `Cache-Control: no-cache`、`X-Accel-Buffering: no`；代理应透传并及时刷新事件。

重连使用最后已消费的事件 ID 作为 `?after=`，不是只发送 `Last-Event-ID` 请求头。重放缓冲可能把早期增量折叠为完整 `message_delta`/`message_done` 快照，客户端必须支持快照合并和按 ID 去重。`message_done` 不能替代 `run_done` 判断运行成功：可展示终态消息的失败运行仍有失败执行状态。

run 的 `status` 为 `active`、`completed`、`cancelled`、`failed`；持久 turn 的 `executionState` 为 `running`、`succeeded`、`cancelled`、`failed`。终态错误类型为 `AGENT_PROVIDER_AUTH_ERROR`、`AGENT_PROVIDER_ERROR`、`AGENT_PROVIDER_TIMEOUT`、`AGENT_INTERNAL_ERROR`、`AGENT_RUN_CANCELLED`、`AGENT_EDIT_TRANSACTION_INCOMPLETE`。

`AgentSessionResponse` 包含 `resumeId`、`revision`、`messages`、`executions`。`executions` 保存 run/turn ID、模型身份快照、起止时间和执行结果。`recovery` 在同一恢复流程中返回权威 session 及匹配的活动 run；没有活动 run 时 `run: null`。运行和 SSE 重放属于当前后端进程，重启后不能接回旧执行；后端启动会将中断的持久执行标记失败，历史仍由 session 接口读取。

会话 PUT 使用 `revision` 乐观并发控制，替换产品历史并清理对应执行记录与不再引用的附件；活动运行期间不接受替换。revision 过期返回 409 `AGENT_SESSION_REVISION_CONFLICT`；重复 turn 或消息身份冲突返回 `AGENT_SESSION_TURN_CONFLICT`。收到这些错误后应读取 recovery/session，以服务端状态协调界面，不盲目覆盖。

### 草稿审核与应用

assistant 的 `transactionState` 为 `none`、`provisional`、`committed`、`rolled_back`。只有完成的草稿事务可进入审核；流中的 provisional edits 不代表正式内容已经保存。编辑 operation 的具体字段与允许路径以 [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) 为准。

`draft.baseResume` 保存草稿依据，`draft.reviewItems` 将有序 edits 分成可独立审核的组；每项有 `id`、`editIds`、`status`。编辑 ID 必须恰好覆盖一次且保持顺序。review item 状态为 `pending`、`applied`、`discarded`、`superseded`；客户端审核命令只能提交 `applied` 或 `discarded`。

丢弃选中审核项的请求示例：

```json
{
  "revision": "当前session revision",
  "status": "discarded",
  "reviewItemIds": ["待审核项ID"]
}
```

应用时改用 `status: "applied"`，并提交 `expectedVersionId` 和 `resume`。其中 `resume` 必须是符合正文 schema 的完整合并候选。前端根据草稿与当前编辑器内容生成可审核结果，用户确认后调用此命令。

应用时 `revision`、`expectedVersionId` 同时防止覆盖新的会话决定或正式简历；后端在一个事务中写入简历 autosave 和审核状态。响应 `resume` 为保存后的 `ResumeDetailResponse`。丢弃请求只提交 `revision`、`status: "discarded"`、非空 `reviewItemIds`，禁止提交 `resume` 或 `expectedVersionId`，响应 `resume: null`。

review item ID 必须唯一并指向待审核项。冲突使用 HTTP 409：`AGENT_SESSION_REVISION_CONFLICT`（可含新 `revision`）、`RESUME_VERSION_CONFLICT`（含 `versionId`）、`AGENT_RUN_CONFLICT`（可含 `runId`）、`AGENT_DRAFT_DECISION_CONFLICT`（可含 `revision`、`status`）。这些附加字段位于 envelope 的 `data` 中。

### 附件

附件先上传，再在用户消息 `files` 中引用返回的后端附件 ID 与元数据。上传响应为 `id`、`filename`、`mediaType`、`kind: "text" / "image"`；不要把浏览器临时 URL 当作持久引用。附件归属于指定简历的 Agent 会话，不能跨简历复用。

支持文本、PDF、DOCX 与经内容识别的图片。单附件最多 10 MiB，provider 上下文最多五个附件，合计最多 20 MiB；单文件提取文本最多 250,000 字符、请求合计最多 400,000 字符，PDF 最多 50 页。具体格式识别与限制见 [attachments.py](../backend/app/services/agent/attachments.py)。这些 provider 请求限制不用于裁剪已保存的历史引用。

发送前可 DELETE 取消上传；已发送的历史附件不可通过该接口删除。未发送附件在 24 小时后可被后台清理；已发送附件随历史引用和所属简历生命周期管理。下载返回原始文件并要求 Bearer。
