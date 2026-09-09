# Reseno 项目概览

## 产品范围

Reseno 是可自行部署的单 owner 简历工作区，提供结构化编辑、模板、导入导出和
Agent 辅助修改。业务数据保存在实例本地，模型请求使用 owner 配置的服务。
一个实例只有一个账号，不提供多人协作或多租户空间。

安装、启动和环境配置见 [README](../README.md)，HTTP 接口与数据契约见
[API 文档](API.md)。本文说明产品行为、模块职责和运行约束。

| 能力 | 当前行为 |
| --- | --- |
| 账号 | 首次创建 owner；密码登录，可绑定实例自己的 GitHub App；同源标签页同步会话，编辑中认证失效可重新登录并继续操作 |
| 简历 | 创建、复制、搜索、分页、结构化编辑、自动保存、手动检查点、历史版本、回收站 |
| 编辑 | 基本信息、头像裁剪、自定义联系字段；教育、经历、项目、出版物、成就和通用列表；模块排序、折叠和行内富文本 |
| 模板 | Minimal、Modern、Compact、Classic、Executive、Academic 六个内置模板；可创建自定义副本，编辑布局、字体、颜色和装饰图片 |
| 预览 | 共享 A4 渲染、分页和缩放；模板试览、图片定位、智能一页适配，以及 Agent 草稿差异预览 |
| 导入导出 | 导入简历与模板 JSON，在浏览器中解析 PDF；导入支持取消、保留已成功部分和重试；导出 JSON、PDF、单页 PNG 或多页图片 ZIP |
| Agent | 对话、附件、模型选择、公开网页检索、结构化编辑草稿、逐项审核、继续修改、停止和断线重连 |
| 语言与外观 | 中文与英文界面；简历语言独立于界面语言，默认模板按简历语言分别保存；浅色、深色和跟随系统主题 |

PDF 导入提取可读取文本并解析结构，不能把所有版式或扫描图片都保证还原为原始文档。
Agent 的内容质量取决于输入事实、模型和外部信息；建议先形成可审核草稿，由用户确认。

## 模块与入口

前端使用 React、TypeScript、Vite、Tailwind CSS 和 shadcn/ui，包管理器为 pnpm；
后端使用 Python、FastAPI、SQLite 和 uv。

| 位置 | 职责 |
| --- | --- |
| [frontend/src/App.tsx](../frontend/src/App.tsx) | 认证入口、路由与页面加载边界 |
| [frontend/src/components/workspace](../frontend/src/components/workspace) | 页面查询、路由切换、保存和离开事务 |
| [frontend/src/components/editor](../frontend/src/components/editor) | 简历结构化编辑与富文本输入 |
| [frontend/src/components/preview](../frontend/src/components/preview) | 简历、模板与导出共用的文档预览和分页 |
| [frontend/src/components/templates](../frontend/src/components/templates) | 模板目录和自定义模板编辑 |
| [frontend/src/components/copilot](../frontend/src/components/copilot) | Agent 会话、流式事件、草稿审核和运行状态 |
| [frontend/src/lib](../frontend/src/lib) | API 客户端、领域操作、导入导出、认证与共享状态逻辑 |
| [backend/app/main.py](../backend/app/main.py) | `create_app` 应用工厂和资源生命周期 |
| [backend/app/routers](../backend/app/routers) / [schemas](../backend/app/schemas) | HTTP 路由、请求校验与响应模型 |
| [backend/app/services](../backend/app/services) | 简历、模板、认证、导出、模型配置和会话持久化 |
| [backend/app/services/agent](../backend/app/services/agent) | 模型上下文、开放工具循环、证据边界和草稿事务 |
| [backend/app/services/llm](../backend/app/services/llm) | 各 API family 的请求、流式响应与参数适配 |

主要页面为 `/setup`、`/login`、`/resume`、`/resume/:id`、`/templates`、
`/template/:id`、`/trash`、`/models` 和 `/settings`。`/auth/callback` 处理登录返回，
`/pdf-export` 是服务端 Chromium 使用的前端文档渲染页。

工作区页面通过对应的 `/api/workspace/pages/*` 聚合查询取得初始化数据；
后续读写使用简历、模板、模型和 Agent 资源接口。页面查询不保存业务状态。
前端领域客户端复用 [api-client.ts](../frontend/src/lib/api-client.ts) 及其认证、
错误处理和请求核心，组件不另建通信协议。

## 数据与保存语义

简历正文是 `schemaVersion: 2` 的结构化文档，由 `basic` 和 `sections` 组成。
模块以 `kind` 区分 `education`、`experience`、`project`、`publication`、
`achievement` 和 `simple_list`，每类有自己的条目字段。通用列表以单个 `content`
富文本条目保存，其内部项目符号不拆成多个简历条目。受支持的富文本经过统一整理，
不能当作任意 HTML 执行。

简历资源另外保存标题、`documentLocale`、岗位描述、字体设置、模板 ID 和简历级
模板设置覆盖。模板的预设、布局、字体和视觉设置属于独立资源。
内置模板只读，自定义副本可以编辑。

- 简历自动保存只保留最新临时版本；手动保存形成正式检查点，版本列表展示正式检查点。
  内容相同的保存不会重复创建版本。
- 自定义模板自动保存保留显式保存的检查点。手动保存确认当前模板，放弃修改恢复检查点。
- 导出先保存当前简历，再按返回的版本标识读取文档，避免导出落后的内容。
- 移入回收站与永久删除是不同操作；永久删除需要资源已经处于删除状态。
- 浏览器保留认证会话、界面偏好和运行中的编辑状态；持久化业务数据由后端管理。

## 契约的权威来源

| 契约 | 权威文件 | 前端对应入口 |
| --- | --- | --- |
| 简历文档 | [resume_document.schema.json](../backend/app/services/resume_document.schema.json) | [types/resume.ts](../frontend/src/types/resume.ts) |
| 模块种类与字段 | [section_registry.json](../backend/app/services/agent/section_registry.json) | `/api/section-registry` 与 [resume-sections.ts](../frontend/src/lib/resume-sections.ts) |
| Agent 编辑操作 | [resume_edit_operation.schema.json](../backend/app/services/agent/resume_edit_operation.schema.json) | [resume-edit-operation.generated.ts](../frontend/src/types/resume-edit-operation.generated.ts) |
| 内置模板 | [template_presets.json](../backend/app/services/template_presets.json) | [template-presets.generated.ts](../frontend/src/lib/template-presets.generated.ts) |
| HTTP 请求与响应 | [backend/app/schemas](../backend/app/schemas) 和路由实现 | [types/api.ts](../frontend/src/types/api.ts) 及领域客户端 |

在 `frontend` 中运行 `pnpm generate:agent-contract` 和
`pnpm generate:template-presets` 更新对应生成产物。文档说明行为与调用方式，
完整字段和操作变体以这些契约为准。

## Agent 与模型

Agent 的核心产物是可预览、可应用或可丢弃的草稿。模型从当前文档、用户输入、
附件和会话上下文出发，自主选择直接回答或调用工具；工具结果返回同一循环，
模型自然结束时完成本轮。系统不把分析、搜索、编辑和总结固化成阶段顺序。

本地工具包括 `web_search`、`web_fetch` 和 `edit_execute`；启用 provider 原生检索时，
由原生检索替代本地 Web 工具。`suggestOnly` 模式不开放编辑工具。
公开网页是外部参考，不能作为候选人职责、指标或经历的事实证据。
模型上下文对个人信息做脱敏，编辑引擎校验隐私、事实来源和文档结构。
具体上下文与工具行为见 [runtime](../backend/app/services/agent/runtime)、
[environment.py](../backend/app/services/agent/environment.py) 和
[draft/engine.py](../backend/app/services/agent/draft/engine.py)。

编辑批次先进入 `provisional`。本轮成功结束后形成 `committed` 待审核草稿；
这里的提交只指 Agent 事务完成。正式简历的修改仍需用户审核确认。
取消、未修复的工具拒绝或运行失败会回滚未完成的事务。
会话 revision 用于拒绝并发覆盖，继续修改草稿保留原始基线以便差异比较和冲突处理。

聊天采用 SSE，客户端按事件序号恢复订阅；HTTP 连接中断不会自动取消已接受的 run。
会话和最终执行状态持久化，正在执行的模型请求及事件重放缓冲属于当前进程。
后端重启不会继续原来的 provider 请求。

模型配置区分云端 provider、本地运行时和自定义 API。`provider` 表示服务身份，
`apiFamily` 选择 `openai_responses`、`openai_compatible_chat`、
`anthropic_messages` 或 `google_gemini` 适配器。Provider 清单与默认地址由
[model_providers.py](../backend/app/services/model_providers.py) 提供。

模型发现结果和补充能力元数据分别缓存；补充元数据由 LiteLLM 与 models.dev
合并快照提供。元数据描述能力，协议适配器负责实际请求格式。
Thinking 使用 `thinkingMode: auto | off`，可选范围由 `availableThinkingModes`
返回，只有能力与协议适配均支持时才提供 Off。
API Key 在后端加密存储，客户端仅取得预览值。

## 运行与数据约束

应用工厂负责配置与密钥初始化，应用生命周期负责数据库校验、恢复操作和资源关闭。
默认数据目录为 `~/.reseno`：业务数据库是 `app.db`，账号与认证数据是 `auth.db`，
文档、附件及临时导出位于 `storage`，用户设置位于 `user_settings.json`。
具体路径覆盖项见 [backend/.env.example](../backend/.env.example)。

首次启动缺失的加密与签名密钥会写入配置文件。已有数据库缺少密钥时必须恢复原密钥，
备份需要同时保留配置密钥、数据库和存储。启动校验遇到不兼容的数据库结构会保留数据
并拒绝启动，不自动迁移或重建已有数据库。

每个工作区使用一个 worker 和一个副本。后端在运行期间对业务数据库、认证目录和
存储目录持有独占文件锁，存储必须支持该锁语义。Agent run 与渲染器由该进程管理。

PDF 和图片由后端复用的 Chromium 串行渲染，每个请求使用独立浏览器上下文，
运行中与排队的导出请求合计最多四个。渲染器访问 `FRONTEND_RENDER_BASE_URL`
下的 `/pdf-export`；生产静态托管需要支持该路由的直接访问与 SPA 回退。
前端与 `/api` 宜使用同源代理，远端 GitHub 登录需要 HTTPS。
首次 owner 创建仅接受回环客户端。导出下载需要认证，临时文件有过期时间。

公开 Swagger、ReDoc 和 `/openapi.json` 端点关闭；内部工具可从应用实例的
`app.openapi()` 读取生成的 HTTP Schema。

## 开发与验证

依赖版本以 [frontend/package.json](../frontend/package.json)、
[backend/pyproject.toml](../backend/pyproject.toml) 及其锁文件为准。
[质量工作流](../.github/workflows/frontend-quality.yml) 使用 Node 24、pnpm 11.9.0
和 Python 3.13；Python 项目最低要求为 3.12。

| 工作目录 | 命令 | 用途 |
| --- | --- | --- |
| `frontend` | `pnpm install --frozen-lockfile` | 安装锁定的前端依赖 |
| `frontend` | `pnpm check:frontend` | 格式、源码预算、Lint、类型、行为和生产 bundle 检查 |
| `frontend` | `pnpm test:workspace-network:smoke` | 关键工作区浏览器回归 |
| `backend` | `uv sync --locked --all-groups` | 安装锁定的后端与开发依赖 |
| `backend` | `uv run --locked ruff check .` | Python 静态检查 |
| `backend` | `uv run --locked mypy app` | Python 类型检查 |
| `backend` | `uv run --locked pytest -q` | 默认后端测试集 |
| `backend` | `RUN_BROWSER_E2E=1 uv run --locked pytest tests/e2e -q` | 浏览器完整测试集 |

浏览器测试需要安装 Playwright Chromium。未设置 `RUN_BROWSER_E2E=1` 时跳过的
浏览器测试不计为验证通过；CI 的 smoke 覆盖与完整 E2E 是不同范围。
测试使用隔离数据目录，前后端服务分别在 `frontend` 和 `backend` 中启动。
