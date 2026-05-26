# ResuMate Frontend API Contract

## 基础约定

前端 API 入口集中在 `frontend/src/lib/api-client.ts`。

- 如果设置 `VITE_API_BASE_URL`，请求真实后端。
- 如果未设置，默认请求同源 `/api`；Vite 开发环境通过代理转发到本地后端。
- 前端不再读取静态 mock JSON，也不再用浏览器本地存储保存业务快照。

统一响应格式：

```ts
type ApiResponse<T> = {
  code: number
  message: string // stable i18n key, for example "OK" or "UNAUTHORIZED_REQUEST"
  data: T
  requestId?: string
}
```

HTTP 层用于表示请求是否成功到达后端；业务状态统一放在 payload 中。正常业务错误
也返回 HTTP 200，前端只按 `code` 分支处理，避免 HTTP 状态码和业务状态混用。

常用业务码：

```ts
const ApiCode = {
  ok: 0,
  badRequest: 40000,
  unauthorized: 40001,
  validationError: 40002,
  notFound: 40004,
  internalError: 50000,
}
```

成功时 `code = 0`。后端应保持该 envelope，避免前端大范围改动。
`message` 不返回中文或英文句子，只返回稳定映射 key；前端根据当前语言做 i18n
展示。

## Auth

### POST `/api/auth/login`

用途：由后端校验用户名和密码。前端只接收成功或失败结果，不读取后端明文凭据。
登录成功后返回 8 小时有效的 Bearer JWT。

JWT 校验只在后端 `APP_ENV=production` 时启用；`development` 下后端不会拦截缺失
或过期的 JWT，前端开发服务器也不会因为缺少本地 token 强制跳转登录页。

请求：

```ts
type AuthLoginRequest = {
  username: string
  password: string
}
```

响应数据：

```ts
type AuthLoginResponse = {
  username: string
  accessToken: string
  expiresAt: string
  tokenType: "bearer"
}
```

### POST `/api/auth/refresh`

用途：使用当前有效 JWT 刷新登录状态。前端每 4 小时调用一次。刷新成功后，
后端会把刷新前的 token 哈希写入 4 小时内存失效缓存；后续任何请求继续携带
旧 token 都会被中间件拦截。

请求头：

```http
Authorization: Bearer <accessToken>
```

响应数据同 `AuthLoginResponse`。

### POST `/api/auth/password`

用途：修改登录密码。前端只提交当前密码和新密码，后端完成校验并写入运行时
`.env` 的 `AUTH_PASSWORD`。修改成功后，后端会让当前 JWT 失效，前端清理本地
session 并跳转登录页。

请求头：

```http
Authorization: Bearer <accessToken>
```

请求：

```ts
type AuthPasswordUpdateRequest = {
  currentPassword: string
  newPassword: string
  confirmPassword: string
}
```

响应数据：

```ts
type AuthPasswordUpdateResponse = {
  username: string
  updated: true
}
```

生产环境下，除 `/api/auth/login` 外，所有 `/api/*` 接口都需要携带
`Authorization: Bearer <accessToken>`。缺失、过期、签名错误或已被刷新失效的
token 会返回 HTTP 200，但 payload 为：

```ts
{
  code: 40001,
  message: "UNAUTHORIZED_REQUEST",
  data: {
    loginUrl: "/login",
    reason: "missing_token" | "invalid_or_expired_token"
  }
}
```

前端收到 `code = 40001` 后清理本地 session 并跳转登录页。

## Workspace

### GET `/api/workspace/bootstrap?locale=zh|en`

用途：初始化整个工作区。

响应数据：

```ts
type WorkspaceBootstrapResponse = WorkspacePayload
```

核心字段：

```ts
type WorkspacePayload = {
  resumes: ResumeWorkspaceItem[]
  defaultTemplateId: string
  customTemplates: ResumeTemplateDefinition[]
  deletedResumes?: ResumeWorkspaceItem[]
  deletedTemplates?: ResumeTemplateDefinition[]
  modelConfigs?: ModelConfig[]
  modelConfig?: ModelConfig
  agentSettings?: AgentSettings
}
```

### PUT `/api/workspace/snapshot`

用途：保存前端提交的工作区数据。后端不会把完整 `resumes` 数组作为
workspace snapshot 存入 SQLite；每份简历会拆分为独立版本 JSON 文件。

请求：

```ts
type WorkspaceSaveRequest = {
  snapshot: WorkspaceSnapshot
}
```

响应：

```ts
type WorkspaceSaveResponse = {
  savedAt: string
  versionId: string
}
```

说明：前端通过保存按钮或 `Ctrl/Cmd + S` 调用该接口。后端按简历 id 保存：

```text
SQLite:
  resumes(id, locale, current_version_id, title, saved_at, deleted, purged, ...)
  resume_versions(resume_id, version_id, content_hash, saved_at, ...)
  templates(id, locale, name, saved_at, deleted, purged, ...)

Storage:
  resumes/{resume_id}/versions/{version_id}.json
  templates/{template_id}/current.json
```

`version_id` 是每份简历从 `1` 开始递增的整数。保存时会计算简历内容 hash；
如果和当前版本一致，不新增 JSON 版本。`updatedAt` / `savedAt` 这类时间戳
不参与 hash，避免空保存制造新版本。
自定义模板使用相同的“SQLite 元信息 + Storage JSON”模式，但不做版本控制；
每个模板只保存当前 JSON。

### GET `/api/workspace/versions`

用途：列出当前可切换的简历版本号。版本号来自 `resume_versions.version_id`。

响应：

```ts
type WorkspaceVersionsResponse = {
  versions: Array<{
    versionId: string
    savedAt: string
  }>
}
```

### GET `/api/workspace/versions/{versionId}`

用途：按版本号读取简历 JSON 并组装为前端需要的 workspace 数据。

响应：

```ts
type WorkspaceVersionResponse = {
  versionId: string
  snapshot: WorkspaceSnapshot
}
```

## PDF Export

### POST `/api/exports/resume-pdf`

用途：基于刚保存的简历版本生成 PDF。前端点击导出时必须先调用
`PUT /api/workspace/snapshot` 保存当前版本，再调用该接口；PDF 生成由后端完成，
前端不再在浏览器内渲染 PDF。

请求：

```ts
type ExportResumePdfRequest = {
  resumeId: string
  locale: "zh" | "en"
  fileNameSeed: string
  savedAt: string
  versionId?: string
  renderBaseUrl?: string // 前端当前 origin，后端用于打开 PDF 专用渲染页
}
```

响应：

```ts
type ExportResumePdfResponse = {
  exportId: string
  downloadUrl: string
  fileName: string
  expiresAt?: string
}
```

后端流程：

```txt
加载 resumeId 对应的 savedAt/versionId 数据
打开前端 /pdf-export 专用渲染页面
用 Playwright 等待字体、图片和页面稳定标记
调用 page.pdf 生成 PDF
将 PDF 写入对象存储或临时下载目录
返回 downloadUrl
```

PDF 专用渲染页面复用前端 A4 预览的结构化数据和模板配置，但隐藏编辑器、
工具栏、Agent 面板等交互 UI。

## Resume Import

### POST `/api/import/resume`

用途：上传 JSON/PDF/文本等文件并生成简历数据。

请求：`multipart/form-data`

```ts
file: File
```

响应：

```ts
type ImportResumeResponse = {
  resumes: ResumeWorkspaceItem[]
}
```

当前后端支持 JSON 文件导入；PDF/文本自动生成仍是待实现能力。

## Template Import

### POST `/api/import/templates`

用途：上传模板文件并生成模板数据。

请求：`multipart/form-data`

```ts
file: File
```

响应：

```ts
type ImportTemplatesResponse = {
  templates: ResumeTemplateDefinition[]
}
```

## Agent

### POST `/api/agent/chat`

用途：发送当前简历上下文、JD、模型配置和用户输入，返回 Agent 建议。
同一个接口同时支持普通 JSON 和 SSE 流式响应。
Agent 使用 `plan_execute` 范式：先解析 JD 来源和简历上下文，再生成计划，
最后返回可执行的结构化修改操作。前端只把这些操作应用到临时 JSON 草稿，
用户确认后才写回当前简历。
后端会使用 SQLite 中已配置并加密保存的大模型配置发起真实模型调用；如果没有
可用模型配置，接口只返回配置引导，不返回模拟对话。

请求头：

```txt
Content-Type: application/json
Accept: application/json | text/event-stream
```

当 `stream: true` 且 `Accept: text/event-stream` 时，后端返回 SSE；否则返回普通 JSON。
前端只渲染后端返回的 Agent 消息数据，不再内置示例对话、工具调用或固定建议。

请求：

```ts
type AgentChatAttachment = {
  id?: string
  filename?: string
  mediaType?: string
  url?: string // data URL 或后端可访问的上传文件 URL
}

type AgentConversationMessage = {
  id?: string
  role: "user" | "assistant"
  text: string
  files?: AgentChatAttachment[]
  createdAt?: string
}

type AgentChatRequest = {
  resumeId?: string // 当前简历 ID；Agent 会话按 resumeId 存储和检索
  prompt: string
  message?: AgentConversationMessage // 当前用户消息
  messages?: AgentConversationMessage[] // 最近可见多轮消息，前端当前发送最近 12 条
  conversation: Array<{
    role: "user" | "assistant"
    text: string
  }> // legacy 兼容字段，后端可优先读取 messages
  files: AgentChatAttachment[]
  locale: "zh" | "en"
  resume: ResumeData
  jobBrief: string
  keywordMatch: {
    matched: string[]
    missing: string[]
    score: number
  }
  appliedActions: string[]
  modelConfig: ModelConfig | null
  settings: AgentSettings
  stream?: boolean
}
```

普通 JSON 响应：

```ts
type AgentChatActionId = "summary" | "bullet" | "keywords" | "plan" | "execute"

type AgentSource = {
  id: string
  title: string
  sourceType: "resume" | "jobBrief" | "attachment" | "web" | "system"
  url?: string
  excerpt?: string
}

type AgentToolInvocation = {
  id: string
  type: string
  title: string
  state:
    | "input-streaming"
    | "input-available"
    | "output-available"
    | "output-error"
    | "approval-requested"
    | "approval-responded"
    | "output-denied"
  input?: unknown
  output?: unknown
  errorText?: string
  startedAt?: string
  completedAt?: string
}

type AgentResumeEditSuggestion = {
  id: string
  title: string
  target: string // 例如 basic.summary 或 sections.project.items[0]
  reason: string
  replacement?: string
  status?: "planned" | "executed" | "rejected"
  operation?: ResumeEditOperation
}

type ResumeEditOperation =
  | { type: "replace_field"; path: string; value: string | string[] }
  | { type: "insert_section"; section: ResumeSection; index?: number }
  | { type: "update_section"; sectionId: string; patch: Partial<ResumeSection> }
  | { type: "delete_section"; sectionId: string }
  | { type: "reorder_sections"; sectionIds: string[] }
  | { type: "insert_item"; sectionId: string; item: ResumeSectionItem; index?: number }
  | { type: "update_item"; sectionId: string; itemId: string; patch: Partial<ResumeSectionItem> }
  | { type: "delete_item"; sectionId: string; itemId: string }
  | { type: "reorder_items"; sectionId: string; itemIds: string[] }

type AgentChatResponse = {
  message: {
    id: string
    role: "assistant"
    tone?: "default" | "success"
    text: string
    reasoning?: string
    suggestions?: string[]
    knowledge?: Array<{
      title: string
      detail: string
    }>
    tools?: AgentToolInvocation[]
    sources?: AgentSource[]
    edits?: AgentResumeEditSuggestion[]
    quickReplies?: string[]
    actions?: AgentChatActionId[]
  }
}
```

SSE 流式响应事件：

```ts
type AgentChatStreamEvent =
  | {
      type: "message_start"
      message: Partial<Pick<AgentChatResponse["message"], "id" | "role" | "tone" | "text">>
    }
  | {
      type: "text_delta"
      delta: string
    }
  | {
      type: "reasoning_delta"
      delta: string
    }
  | {
      type: "message_delta"
      message: Partial<Omit<AgentChatResponse["message"], "id" | "role">>
    }
  | {
      type: "message_done"
      message: AgentChatResponse["message"]
    }
  | {
      type: "error"
      message: string
    }
```

推荐事件顺序：

```txt
event: message_start
data: {"type":"message_start","message":{"id":"agent-msg-xxx","role":"assistant","tone":"default"}}

event: reasoning_delta
data: {"type":"reasoning_delta","delta":"正在分析用户意图和当前简历上下文。"}

event: text_delta
data: {"type":"text_delta","delta":"第一段增量文本"}

event: text_delta
data: {"type":"text_delta","delta":"，继续输出"}

event: message_delta
data: {"type":"message_delta","message":{"sources":[{"id":"source-current-resume","title":"当前简历","sourceType":"resume"}],"tools":[{"id":"tool-1","type":"tool-resume_keyword_match","title":"resume_keyword_match","state":"output-available","input":{"missing":["TypeScript"]},"output":{"missingCount":1}}],"edits":[{"id":"edit-1","title":"补强个人简介","target":"basic.summary","reason":"简介缺少结果证明","replacement":"..."}],"quickReplies":["继续优化项目经历"],"suggestions":["建议 1"],"actions":["summary","bullet"]}}

event: message_done
data: {"type":"message_done","message":{"id":"agent-msg-xxx","role":"assistant","tone":"default","text":"完整文本","reasoning":"完整 reasoning 文本","sources":[],"tools":[],"edits":[],"quickReplies":[],"suggestions":["建议 1"],"actions":["summary","bullet"]}}
```

约束：

- `message_done.message.text` 必须是完整文本，不能只返回最后一个 delta。
- `reasoning_delta` 只用于 provider 显式返回的 reasoning 内容；前端用
  AI Elements reasoning 组件展示，不参与普通正文拼接。
- `actions` 只返回 action id，按钮文案由前端本地 i18n 渲染。
- `tools` 用于 AI Elements 的工具调用展示；同一个工具调用的 `id` 在流式过程中应保持稳定。
- `sources` 用于引用来源展示；如果来源可打开，返回 `url`，否则只返回标题和摘要。
- `edits` 是结构化修改建议，当前只展示不自动应用；后续自动应用时需要补充 patch/action schema。
- `quickReplies` 是后端建议的继续追问，不要由前端硬编码。
- `message` 是当前用户消息，`messages` 用于多轮上下文；`conversation` 仅作为旧字段兼容。
- 传入 `resumeId` 时，后端会把当前用户消息和最终助手消息写入
  `agent_sessions` / `agent_messages`，前端重新进入同一简历时按 `resumeId` 加载。
- 附件 `url` 当前可能是 data URL；大文件接后端后建议先上传，再传后端可访问 URL。
- 后端发生可恢复错误时可发送 `event: error`，也可以直接返回非 2xx JSON error。

### GET `/api/agent/resumes/:resumeId/session`

用途：按简历 ID 加载 Agent 会话历史消息。前端进入简历编辑页时使用当前
`resumeId` 拉取记录，并继续把最近消息传给 `/api/agent/chat` 作为上下文。

响应：

```ts
type AgentStoredMessage = AgentConversationMessage & {
  response?: AgentChatResponse["message"]
}

type AgentSessionResponse = {
  resumeId: string
  messages: AgentStoredMessage[]
}
```

## Reserved CRUD Routes

以下路由已在前端集中定义，后端可按需实现。当前产品的公开接口仍使用
workspace 聚合读写，但后端内部已经按简历 id/version 拆分保存。

```txt
GET    /api/resumes
POST   /api/resumes
GET    /api/resumes/:id
PUT    /api/resumes/:id
DELETE /api/resumes/:id

GET    /api/templates
POST   /api/templates
GET    /api/templates/:id
PUT    /api/templates/:id
DELETE /api/templates/:id

GET    /api/model-configs
POST   /api/model-configs
PUT    /api/model-configs/:id
DELETE /api/model-configs/:id

GET    /api/agent/settings
PUT    /api/agent/settings
```

## Core Data Shapes

### ResumeWorkspaceItem

```ts
type ResumeWorkspaceItem = {
  id: string
  title: string
  updatedAt: string
  resume: ResumeData
  jobBrief: string
  typography?: ResumeTypography
  template?: BuiltinResumeTemplateId | ResumeTemplateDefinition
}
```

### ResumeData

```ts
type ResumeData = {
  basic: ResumeBasicInfo
  sections: ResumeSection[]
}
```

### ResumeBasicInfo

```ts
type ResumeBasicInfo = {
  name: string
  headline: string
  phone: string
  email: string
  location: string
  avatar?: string
  summary?: string
  customFields: Array<{
    id: string
    label: string
    value: string
  }>
}
```

### ResumeSection

```ts
type ResumeSection = {
  id: string
  kind: "education" | "internship" | "project" | "other" | "custom"
  layout: "timeline" | "list"
  customTitle?: string
  items: ResumeSectionItem[]
}
```

### ResumeTemplateDefinition

```ts
type ResumeTemplateDefinition = {
  id: string
  preset: "minimal" | "modern" | "compact"
  name: string
  description: string
  layout: ResumeTemplateLayout
  typography: ResumeTypography
  settings: ResumeTemplateSettings
  updatedAt: string
  isBuiltIn?: boolean
}
```

### ModelConfig

```ts
type ModelConfig = {
  id: string
  provider: string
  nickname?: string
  apiKeyPreview: string
  model: string
  apiUrl: string
  temperature: number
  topP: number
  maxTokens: number | null
  systemPrompt: string
}
```

`apiKeyPreview` 由后端生成，只返回前 6 位加固定 `****`，例如
`sk-edA****`。接口响应不返回真实 API Key，也不通过占位长度暴露真实
Key 长度。

### GET `/api/model-configs`

用途：返回 SQLite 中已启用的大模型配置。API Key 只返回 `apiKeyPreview`。

响应数据：

```ts
type ModelConfigsResponse = {
  configs: ModelConfig[]
}
```

### POST `/api/model-configs`

用途：创建或更新大模型配置。请求可携带一次性明文 `apiKey`，后端使用
`.env` 中的 `RESUMATE_MASTER_KEY` 加密后写入 SQLite；明文只在当前请求内
使用，不写入日志、不返回前端。

请求：

```ts
type ModelConfigUpsertRequest = {
  id: string
  provider: string
  nickname?: string
  apiKey?: string
  model: string
  apiUrl: string
  temperature?: number
  topP?: number
  maxTokens?: number | null
  systemPrompt?: string
  isDefault?: boolean
}
```

响应数据：

```ts
type ModelConfigUpsertResponse = ModelConfig
```

### DELETE `/api/model-configs/{id}`

用途：删除模型配置。后端执行软删除，将该配置标记为 disabled，不返回或删除
密钥明文。

响应数据：

```ts
type ModelConfigDeleteResponse = {
  id: string
}
```

### AgentSettings

```ts
type AgentSettings = {
  defaultModelId?: string
  responseLanguage: "zh" | "en"
  behaviorMode: string
  autoRunMatch: boolean
}
```

## Backend Integration Checklist

- 保持统一 `ApiResponse<T>` envelope。
- 支持 `VITE_API_BASE_URL` 作为前端后端切换开关。
- 先实现 workspace bootstrap/snapshot 可最快接入。
- 文件上传接口需要支持 multipart。
- 生产环境不要返回明文认证配置；任何环境都不要返回明文 API Key。
- Agent 普通 JSON 和 SSE 流式响应格式已固定，后端可先返回 JSON，再切到 SSE。
- 如果拆分 CRUD，前端 helper 应该统一适配，避免 UI 组件直接拼接接口。

## Runtime Data And Environment

后端通过环境变量配置运行时数据路径，默认不把数据库、导出文件、上传文件
或真实 `.env` 当作源码。未设置 `APP_ENV_FILE` 时，真实 `.env` 默认位于
`APP_DATA_DIR/.env`，本地即 `~/.resumate/.env`：

```env
APP_ENV=development
APP_DATA_DIR=~/.resumate
APP_DB_PATH=~/.resumate/app.db
APP_STORAGE_DIR=~/.resumate/storage
APP_HOST=127.0.0.1
APP_PORT=8000
FRONTEND_RENDER_BASE_URL=http://127.0.0.1:5173
PDF_RENDER_TIMEOUT_MS=30000
AUTH_USERNAME=admin
AUTH_PASSWORD=ResuMate@2026
BACKEND_CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
# RESUMATE_MASTER_KEY 在 .env.example 中留空，真实 .env 首次启动自动填充
RESUMATE_MASTER_KEY=
# RESUMATE_JWT_SECRET 在 .env.example 中留空，真实 .env 首次启动自动填充
RESUMATE_JWT_SECRET=
```

SQLite 中的大模型配置保存非敏感字段、`encrypted_api_key` 和固定长度
`api_key_preview`。真实 `.env` 缺失时后端会在运行时数据目录中从
`backend/.env.example` 生成一份，再把 `RESUMATE_MASTER_KEY` 填成 Fernet key
并把 `RESUMATE_JWT_SECRET` 填成随机签名密钥，两者都会标记 `DO NOT CHANGE`；
之后启动如果已经存在有效值，绝不重新生成或覆盖。
如检测到旧版仓库内 `backend/.env`，只会在目标 runtime `.env` 不存在时迁移一次，
避免项目更新覆盖用户密钥。`AUTH_PASSWORD` 首次初始化默认写入 `ResuMate@2026`；
之后可通过设置页调用 `POST /api/auth/password` 修改，也可自行编辑
`APP_DATA_DIR/.env`。通过设置页修改会立即生效；手动编辑 `.env` 后需要重启后端。
