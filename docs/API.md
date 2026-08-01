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

## Workspace 页面查询与资源边界

`/api/workspace/pages/*` 是只读的页面聚合查询（BFF），用于一次返回某个路由
首次渲染需要的上下文。它不是通用 workspace 快照，也不负责资源 CRUD 或版本
管理。每个页面只能调用对应的查询；未知路由不发起 workspace 请求。

原 `/api/workspace/bootstrap`、`/api/workspace/snapshot` 和
`/api/workspace/versions*` 已移除。简历、模板和模型的写操作由各自的资源接口
负责，简历版本也必须带上所属的 `resumeId`。

### 页面查询矩阵

| 页面 | 页面查询 | 职责 |
| --- | --- | --- |
| `/resume` | `GET /api/workspace/pages/resumes` | 有效简历列表和模板目录 |
| `/resume/:id` | `GET /api/workspace/pages/resume-editor` | 编辑器共享的模板、模型和 Agent 设置；简历详情及版本由资源接口读取 |
| `/templates`、`/template/:id` | `GET /api/workspace/pages/templates` | 有效模板目录和默认模板 |
| `/trash` | `GET /api/workspace/pages/trash` | 已删除简历、已删除模板及预览所需的有效模板目录 |
| `/models` | `GET /api/workspace/pages/models` | 模型配置和引用模型的 Agent 设置 |
| `/settings` | `GET /api/workspace/pages/settings` | 设置页所需的模型配置和 Agent 设置 |

PDF 渲染页同样需要模板目录，因此复用 templates 页面查询。共享依赖不表示页面
可以读取无关资源，例如 templates、models 和 settings 查询都不会读取简历列表。

六个页面查询都使用独立的强类型响应模型；响应 `data` 的准确字段如下：

```ts
type WorkspacePageTheme = {
  theme?: "light" | "dark" | "system"
}

type TemplatePageContext = {
  defaultTemplateId: string
  customTemplates: ResumeTemplateDefinition[]
}

type ModelPageContext = {
  modelConfigs: ModelConfig[]
  agentSettings: AgentSettings
}

type ResumesPageResponse = WorkspacePageTheme &
  TemplatePageContext & {
    resumes: ResumeWorkspaceItem[]
  }

type ResumeEditorPageResponse = WorkspacePageTheme &
  TemplatePageContext &
  ModelPageContext

type TemplatesPageResponse = WorkspacePageTheme & TemplatePageContext

type TrashPageResponse = WorkspacePageTheme &
  TemplatePageContext & {
    deletedResumes: DeletedResumeWorkspaceItem[]
    deletedTemplates: DeletedResumeTemplateDefinition[]
  }

type ModelsPageResponse = WorkspacePageTheme & ModelPageContext
type SettingsPageResponse = WorkspacePageTheme & ModelPageContext
```

字段是按页面必需依赖声明的，不再使用“所有字段都可选”的统一
`WorkspacePayload`。后端 response model 会校验并过滤响应字段，前端也按路由
获得对应 DTO。

### Workspace 偏好命令

| 方法 | 路径 | 职责 |
| --- | --- | --- |
| `PUT` | `/api/workspace/user-settings?locale=zh\|en` | 保存主题和 Agent 设置，不保存简历或模板 |
| `PUT` | `/api/workspace/default-template` | 校验模板可用后保存默认模板 ID |

`PUT /api/workspace/user-settings` 的请求体为
`{ settings: { theme?, agentSettings? } }`；
`PUT /api/workspace/default-template` 的请求体为 `{ templateId: string }`，响应
`data` 为 `{ defaultTemplateId: string }`。

### 简历资源与版本

| 方法 | 路径 | 职责 |
| --- | --- | --- |
| `GET` | `/api/resumes?status=active\|deleted` | 按状态列出简历；deleted 返回回收站预览 |
| `POST` | `/api/resumes` | 创建简历及初始版本 |
| `GET` | `/api/resumes/{resumeId}` | 读取一份有效简历的当前版本 |
| `PUT` | `/api/resumes/{resumeId}` | 保存完整简历；内容变化时创建新版本 |
| `POST` | `/api/resumes/{resumeId}/duplicate?locale=zh\|en` | 从当前版本创建独立副本，不复制会话和版本历史 |
| `POST` | `/api/resumes/{resumeId}/trash` | 将有效简历移入回收站，不创建版本 |
| `POST` | `/api/resumes/{resumeId}/restore` | 恢复已删除简历，不创建版本 |
| `DELETE` | `/api/resumes/{resumeId}` | 永久删除已在回收站中的简历及其版本、会话和附件 |
| `DELETE` | `/api/resumes/trash` | 永久清空简历回收站 |
| `GET` | `/api/resumes/{resumeId}/versions` | 列出指定简历的版本摘要 |
| `GET` | `/api/resumes/{resumeId}/versions/{versionId}` | 读取指定简历的一个历史版本 |

简历详情和历史版本都返回：

```ts
type ResumeDetailResponse = {
  resume: ResumeWorkspaceItem
  savedAt: string
  versionId: string
}

type ResumeVersionsResponse = {
  versions: Array<{
    versionId: string
    savedAt: string
  }>
}
```

后端按简历 ID 持久化。`versionId` 从 `1` 开始递增；内容 hash 与当前版本相同
时不会制造新版本，展示时间字段不参与 hash。

```text
SQLite:
  resumes(id, locale, current_version_id, title, saved_at, deleted, ...)
  resume_versions(resume_id, version_id, content_hash, saved_at, ...)

Storage:
  resumes/{resume_id}/versions/{version_id}.json
```

### 模板资源

| 方法 | 路径 | 职责 |
| --- | --- | --- |
| `GET` | `/api/templates?status=active\|deleted` | 按状态列出自定义模板 |
| `POST` | `/api/templates` | 创建后端分配 ID 的自定义模板 |
| `PUT` | `/api/templates/{templateId}` | 更新一份有效的自定义模板 |
| `POST` | `/api/templates/{templateId}/trash` | 将自定义模板移入回收站；若为默认模板则恢复内置默认值 |
| `POST` | `/api/templates/{templateId}/restore` | 恢复已删除模板 |
| `DELETE` | `/api/templates/{templateId}` | 永久删除已在回收站中的模板 |
| `DELETE` | `/api/templates/trash` | 永久清空模板回收站 |

内置模板不能通过模板资源接口修改或删除。自定义模板使用 SQLite 元信息和
`templates/{template_id}/current.json` 保存当前内容，不创建版本历史。

模型配置由 `/api/model-configs` 负责查询、创建或更新、删除；Provider 元数据和
模型发现由 `/api/model-providers*` 负责。模型资源接口的完整契约见后文
“ModelConfig”章节。

## PDF Export

### POST `/api/exports/resume-pdf`

用途：基于刚保存的简历版本生成 PDF。调用方必须先保存当前简历版本，
再调用该接口；PDF 生成由后端完成。

当前前端导出按钮默认通过同源隐藏 iframe 加载 `/pdf-export?print=1`，
并触发浏览器原生打印/保存 PDF 对话框，不依赖该后端接口。

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
Agent 使用 ReAct 范式：模型先理解用户意图，再决定是否调用 JD 获取、JD 搜索、
简历分析、编辑计划或编辑执行工具。每轮遵循 Reasoning → Action → Observation；
每轮只能执行一个 Action，拿到 Observation 后再决定下一步；
Observation 来自工具结果，最后必须通过隐藏的 `finish` action 结束循环。不要默认
先搜索 JD 或分析简历；只有用户提供 JD URL 或明确要求岗位/JD 匹配时才调用 JD 工具。
前端只把返回的结构化修改操作应用到临时 JSON 草稿，用户确认后才写回当前简历。
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
  settings: AgentSettings & {
    maxReActIterations?: number // 可选；默认 5，后端会限制在 1-8
  }
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
  target: string // 例如 basic.summary 或 sections.project.items.project-1
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
    plan?: string[] // 可选审计元数据；默认前端主视图不直接展示内部计划
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
      type: "plan"
      message: Partial<Pick<AgentChatResponse["message"], "plan">>
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

event: plan
data: {"type":"plan","message":{"plan":["检查当前简历内容","定位需要调整的模块","生成可预览草稿","汇总修改结果"]}}

event: tools
data: {"type":"tools","message":{"tools":[{"id":"call-1","type":"tool-resume_analysis","title":"resume_analysis","state":"input-available","input":{}}]}}

event: tools
data: {"type":"tools","message":{"tools":[{"id":"call-1","type":"tool-resume_analysis","title":"resume_analysis","state":"output-available","input":{},"output":{"sectionCount":2}}]}}

event: edits
data: {"type":"edits","message":{"edits":[{"id":"edit-1","title":"补强项目经历","target":"sections.project.items.project-1","reason":"用户要求强化项目结果","replacement":"负责推荐链路优化，点击率提升 12%。"}]}}

event: text_delta
data: {"type":"text_delta","delta":"第一段增量文本"}

event: text_delta
data: {"type":"text_delta","delta":"，继续输出"}

event: message_delta
data: {"type":"message_delta","message":{"sources":[{"id":"source-jd-url","title":"目标岗位 JD","sourceType":"web","url":"https://example.com/job"}],"tools":[{"id":"call-1","type":"tool-resume_analysis","title":"resume_analysis","state":"output-available","input":{},"output":{"sectionCount":2}}],"edits":[{"id":"edit-1","title":"补强项目经历","target":"sections.project.items.project-1","reason":"用户要求强化项目结果","replacement":"负责推荐链路优化，点击率提升 12%。"}],"quickReplies":["继续优化项目经历"],"suggestions":["建议 1"],"actions":["execute"]}}

event: message_done
data: {"type":"message_done","message":{"id":"agent-msg-xxx","role":"assistant","tone":"default","text":"完整文本","reasoning":"完整 reasoning 文本","sources":[],"tools":[],"edits":[],"quickReplies":[],"suggestions":["建议 1"],"actions":["summary","bullet"]}}
```

约束：

- `message_done.message.text` 必须是完整文本，不能只返回最后一个 delta。
- `reasoning_delta` 只用于 provider 显式返回的 reasoning 内容，不参与普通正文拼接；
  前端默认不展示原始 chain-of-thought。主体验只展示“正在阅读简历 / 正在生成草稿”等
  产品化状态、最终回复和修改摘要。
- `actions` 只返回 action id，按钮文案由前端本地 i18n 渲染。
- `plan` 可在可工具化请求的工具事件之前返回，作为审计或调试元数据；默认 Agent 面板主视图不直接展示内部计划，只展示简短确认文案、当前执行 shimmer 和已完成操作折叠行。
- `tools` 的快照用于生成 Codex-like 当前执行状态和完成后的折叠详情；同一个工具调用的 `id` 在流式过程中应保持稳定。
- `tools` 中 `input-available` / `input-streaming` 表示该步骤正在执行。前端主视图只展示当前步骤 shimmer，例如
  “正在阅读简历 / 正在查询岗位参考 / 正在生成草稿”；完成后折叠为
  “已运行 N 条操作”。折叠详情只展示产品化执行文案，不默认展示底层工具名、参数或原始输出。
- `sources` 用于引用来源展示；如果来源可打开，返回 `url`，否则只返回标题和摘要。
- `edits` 是结构化修改建议；后端必须返回 `ResumeEditOperation`，前端先应用到临时草稿并高亮预览。
- 流式过程中 `edit_execute` 完成后可提前发送 `event: edits`，用于同步中间预览；
  应用/撤回按钮只在 `message_done` 之后展示。
- 前端必须把 `edits` 应用到 pending draft，而不是直接写入正式 `resume`；预览区显示
  draft 并用新增、修改、移动、删除的颜色语义标记变更位置。
- `edit_execute` 可直接携带 `edits` 执行，不强制要求先调用 `edit_plan`；如果需要现有模块或条目 ID，模型应先调用 `resume_analysis`。
- `edit_execute.output.observations` 会返回本次草稿操作的目标位置、修改前快照和修改后快照，模型应根据 Observation 判断是否继续修正或调用隐藏 `finish` 结束。
- `finish` 是后端内部 ReAct 结束 action，不作为前端工具卡展示。
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
  kind:
    | "education"
    | "work"
    | "internship"
    | "project"
    | "skills"
    | "awards"
    | "certificates"
    | "languages"
    | "other"
    | "custom"
  layout: "timeline" | "list"
  customTitle?: string
  items: ResumeSectionItem[]
}
```

### ResumeTemplateDefinition

```ts
type ResumeTemplateDefinition = {
  id: string
  preset:
    | "minimal"
    | "modern"
    | "compact"
    | "classic"
    | "executive"
    | "academic"
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
  providerLabel: string
  iconProvider: string
  providerKind: "cloud" | "local" | "custom"
  apiFamily:
    | "openai_responses"
    | "openai_compatible_chat"
    | "anthropic_messages"
    | "google_gemini"
  nickname: string
  apiKeyPreview: string
  model: string
  apiUrl: string
  temperature: number | null
  topP: number | null
  maxTokens: number | null
  contextWindowTokens: number
  supportsImage: boolean
  supportsThinking: boolean
  supportsTools: boolean
  supportsStreaming: boolean
  thinkingEnabled: boolean
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
  id?: string
  provider: string
  providerKind: "cloud" | "local" | "custom"
  apiFamily:
    | "openai_responses"
    | "openai_compatible_chat"
    | "anthropic_messages"
    | "google_gemini"
  nickname?: string
  apiKey?: string
  model: string
  apiUrl: string
  temperature?: number | null
  topP?: number | null
  maxTokens?: number | null
  contextWindowTokens?: number | null
  supportsImage?: boolean
  supportsThinking?: boolean
  supportsTools?: boolean
  supportsStreaming?: boolean
  thinkingEnabled?: boolean
}
```

响应数据：

```ts
type ModelConfigUpsertResponse = ModelConfig
```

### GET `/api/model-providers`

用途：返回后端维护的 provider manifest。前端只用它渲染选项和默认 API
地址，不自行维护云端 provider 清单。

响应数据：

```ts
type ModelProvidersResponse = {
  providers: Array<{
    id: string
    label: string
    kind: "cloud" | "local" | "custom"
    apiFamily: ModelConfig["apiFamily"] | null
    iconProvider: string
    defaultBaseUrl: string
    officialUrl: string
    authRequired: boolean
    supportsModelDiscovery: boolean
    supportsCustomCapabilities: boolean
  }>
}
```

### POST `/api/model-providers/discover-models`

用途：用用户提供的 API Key 和 API 地址即时获取当前 provider 支持的模型
列表。刷新获取的模型列表会写入本地模型发现缓存，普通请求优先返回缓存。

请求：

```ts
type DiscoverModelsRequest = {
  provider: string
  apiFamily?: ModelConfig["apiFamily"]
  apiUrl: string
  apiKey?: string
  configId?: string
  refresh?: boolean
}
```

响应数据：

```ts
type DiscoverModelsResponse = {
  models: Array<{
    id: string
    label: string
    contextWindowTokens: number
    maxOutputTokens: number | null
    supportsImage: boolean
    supportsThinking: boolean
    metadataSource: "provider" | "litellm" | "fallback" | string
  }>
  source: "cache" | "provider"
}
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
  defaultModelId: string
  responseLanguage: "follow" | "zh" | "en"
  behaviorMode: "balanced" | "strict" | "aggressive"
  confirmationMode: "always" | "suggestOnly"
}
```

## Backend Integration Checklist

- 保持统一 `ApiResponse<T>` envelope。
- 支持 `VITE_API_BASE_URL` 作为前端后端切换开关。
- 页面初始化使用职责明确的 `/api/workspace/pages/*` 查询；不要增加通用
  bootstrap，也不要让页面查询承担资源写入或版本管理。
- 简历、模板、模型和 Agent 会话通过各自资源接口读写，组件不要自行拼接路径。
- 文件上传接口需要支持 multipart。
- 生产环境不要返回明文认证配置；任何环境都不要返回明文 API Key。
- Agent 普通 JSON 和 SSE 流式响应格式已固定，后端可先返回 JSON，再切到 SSE。

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
