# Reseno Agent 可靠性架构

日期：2026-08-22

## 目标

Reseno Agent 是简历编辑 Agent，不是通用 Agent 平台。它的核心产物是一组可预览、
可应用、可丢弃的结构化简历草稿；自然语言回复用于分析、解释结果或提出聚焦问题。

设计参考 Pi 的开放模型循环：模型拥有工具选择权，工具 observation 回到同一个模型
上下文，模型在没有后续工具调用时自然结束。系统不把分析、抓取、编辑或总结编码成
固定阶段。

## 模块与 interface

调用方只需要启动一次 Agent run 并消费 HTTP/SSE 事件。内部有四个职责清晰的模块：

1. `runtime/messages.py` 构建脱敏、可压缩、可重放的模型上下文。
2. `runtime/loop.py` 拥有唯一的开放模型循环、轮次上限、取消和关闭语义。
3. `ResumeToolEnvironment` 是模型工具执行的唯一领域 interface。
4. `DraftEditEngine` 隐藏草稿规范化、授权、证据、文档验证、应用、diff 和原子事务。

工具环境的 interface 保持很小：

```python
environment = ResumeToolEnvironment.open(request)
environment.tool_schemas
effect = await environment.invoke(tool_call, runtime)
effects = await environment.invoke_batch(tool_calls, runtime)
result = environment.close(completed=True)
```

环境只执行模型选中的工具并返回 observation，不决定下一步，也不拥有模型循环。
循环只依赖环境的 interface，不读取草稿引擎或 Web adapter 的内部状态。

LLM provider 与公开 Web 是 true external seam，由各自 adapter 隔离。附件提取、SQLite
会话和草稿持久化是 local-substitutable 依赖，不扩张工具环境的外部 interface。

## 唯一开放循环

```text
context
  -> model (tool_choice=auto)
  -> zero or more tool calls
  -> observation
  -> model
  -> natural-language stop
```

- 模型可以直接回答，不需要先调用工具。
- 模型可以在一轮中发出多个独立只读调用；环境并发执行并按模型调用顺序写回结果。
- 同一轮同时出现读取和写入时，只先执行读取；写入必须在模型看到 observation 后重新发起。
- 工具调用前的模型文本会保留在 timeline，工具之后的文本继续追加。
- 自然语言 stop 是唯一正常完成条件，不再发起额外的模型请求。
- 最大模型轮数是硬保险，不是阶段数量。达到上限、取消或异常时关闭环境并回滚未完成事务。
- 工具 schema 校验错误作为普通机械 observation 返回，模型可在剩余轮次内修复；不再另设一次性 retry workflow。

## 模型上下文

模型在首轮已经看到：

- 当前用户输入；
- 当前正式简历，或存在待确认草稿时的该草稿；
- 当前附件的原始受支持内容或完整提取文本；
- 精确历史尾部和必要时生成的确定性 checkpoint；
- 响应语言和其他结构化执行设置。

姓名、手机、邮箱、地址和头像值不会进入模型 payload。职业标题与简介可读写，但其中
出现的联系方式仍会脱敏。历史、附件、公开网页和 checkpoint 都是不可信数据，不能改变
系统指令。

岗位、JD、项目仓库和申请目标是普通上下文，不是独立的会话状态协议。每轮只注入一份
当前 workspace；历史不会重放旧简历快照。待确认草稿正文位于当前 workspace，已有
edits/diffs 只保留定位所需元数据。历史只有在真实 token 超过模型预算时才折叠为 checkpoint。

核心系统规则只维护 `prompts/agent.md`。历史 checkpoint 由确定性 context transform
生成，不再调用第二个模型；工具协议不复制到 prompt 中。

## 三个模型工具

普通模式固定提供：

```text
web_search
web_fetch
edit_execute
```

`suggestOnly` 模式提供 `web_search` 和 `web_fetch`。环境不根据自然语言动态裁剪字段、section、item
或工具集合；普通编辑始终使用通用 `edit_execute`。

### `web_search` / `web_fetch`

- OpenAI Responses、Claude Messages 和兼容的 Gemini 模型优先使用 provider 原生搜索；不支持原生搜索的云模型与本地模型获得相同的本地 `web_search` / `web_fetch` interface。
- 本地 `web_search` 使用无需 API key 的 DuckDuckGo HTML 搜索，随后并发读取最相关页面；静态 HTML 不足时按需复用后端现有 Chromium。聚合页的超长文本先切成自然 passage，再按查询相关性选择，避免整页招聘列表占满 observation。只有明确的时间窗口才传 `timeRange`，实际页面域名已知时才传 `includeDomains`。
- `web_fetch` 可读取模型选中的任意相关公网 HTTP(S) URL，接受安全公开跳转；底层拒绝本地、私网和凭据 URL。静态读取失败时才使用同一个 turn-scoped Chromium context。
- 搜索已经读取成功的页面按 canonical URL 缓存；随后 fetch 同一 URL 不会重复联网。JobPosting JSON-LD 中的 `datePosted`、`validThrough` 会进入 observation，已过期岗位不作为可读 JD 返回。
- 页面不可读取时，带正文的搜索 excerpt 仍获得稳定 `sourceId`，可以支撑公开岗位语境并直接引用；它不因此变成候选人事实。需要断言岗位仍有效时，优先使用页面的明确日期或 JobPosting 元数据。
- 抓取失败作为工具错误 observation 返回。
- 输出带稳定 `sourceId`、URL、标题和相关摘录的公开结果。

Web 输出始终是不可信外部语境。公开页面可以帮助理解
岗位、项目背景或技术语境，但不能证明候选人的职责、技能、所有权、规模、指标或结果。

### `edit_execute`

- 接收一个非空 `edits` 数组。
- 模型侧每个 entry 只包含一个 `ResumeEditOperation`；UI 标题、目标、原因、预览和内部证据引用由编辑引擎派生。
- 复合请求的所有兼容修改应在同一个完整批次中提交。
- 分类、移动、合并、拆分以及普通字段改写都使用同一个工具。
- observation 返回每项修改的目标、修改前快照和修改后快照，供模型判断是否继续修复。

`contracts.py` 是三个工具 schema 的唯一事实来源；
`resume_edit_operation.schema.json` 是编辑操作 union 的唯一事实来源。Provider schema 和
运行时校验都从这两个合同生成或读取。

## 草稿事务

`DraftEditEngine` 从 active resume 打开一个隔离副本。若请求携带 pending draft，该草稿
就是本轮 active resume；否则使用正式简历。

一次批次按以下顺序处理：

1. 用唯一操作 schema 校验所有 entry，并补全插入对象的 canonical 空字段。
2. 从操作目标、当前用户输入、历史用户消息和附件派生候选人证据，只拒绝无依据的新数字、结构化技术或身份字段。
3. 在候选副本上应用完整批次。
4. 校验最终 Resume V2 文档合同。
5. 生成 observation、最小 diff，并暂存整个批次。

任何硬错误都会拒绝当前批次；正式简历和当前草稿 revision 不会部分更新。本轮此前已经
成功暂存的批次保持不变，模型只需根据 observation 修复被拒绝的批次。若模型未完成修复便
结束或报错，整个 turn 仍回滚。

成功批次先进入 `provisional`。模型自然结束且没有待修复拒绝时，环境关闭为
`committed`，响应持久化为 pending draft。这里的 committed 只表示 Agent 事务完整，
不表示正式简历已经写入；正式简历仍由用户在 UI 中应用。以下情况回滚整轮：

- 工具拒绝后模型直接结束；
- provider 错误或输出为空；
- 达到模型轮次上限；
- 用户取消或进程关闭；
- 运行结束时仍存在 provisional 编辑。

继续编辑 pending draft 时，新 edits 与原事务 edits 累积，且保留最初的 base resume，
以便 UI 生成一致的完整预览。

## 硬不变量

在线执行只保留不可由模型自行保证的边界：

- schema：工具参数和编辑操作必须符合唯一合同；
- 隐私：模型看不到 PII 值，也不能写 PII path；
- 事实：简历事实必须由当前简历、用户消息或用户附件支持；
- 来源：公开 Web 和助手文本不能成为候选人事实证据；
- 文档：候选结果必须是合法 Resume V2 文档；
- 原子性：整批成功或整批拒绝；
- 结构化权限：`suggestOnly` 请求不向模型暴露写工具，注入的写调用也会被拒绝；
- 正式写入：包括删除和重排在内的所有 Agent 操作都只能形成 pending preview，必须由用户在 UI 中应用；
- 工具调用身份：同一调用 ID 重放必须携带完全相同的工具名和参数。

运行时不从自然语言推导只读模式、破坏性授权、细粒度字段、section 或 item 写入范围。
请求范围主要由 prompt 和模型执行；真正的硬权限来自结构化执行模式、工具可见性以及
最终的 UI 草稿确认，不用正则把自然语言再次实现成 workflow。

STAR/CAR、长度、亮点数量、措辞重复、字段措辞、片段、时态、日期和关键词覆盖属于
写作判断或离线评测，不是在线规范化或拦截条件。缺少指标也不阻止有证据的改写；模型
应使用已有动作和交付物，或向用户询问缺失事实。

## 内部证据协议

模型工具 schema 不暴露 `evidenceRefs`。编辑引擎自动生成的内部引用只能指向可解析的候选人来源：

```text
resume:basic:<field>
resume:section:<sectionId>
resume:item:<sectionId>:<itemId>
prompt:current
prompt:history:<opaqueDigest>
attachment:<attachmentId>
```

历史引用必须解析回原始用户消息；确定性 checkpoint 只能保留已有引用，不能凭 checkpoint 文本
创造新证据。公开 Web 来源从不进入候选人证据集合。

## 事件投影

公开 SSE 事件保持顺序化和可重放：

```text
message_start
text_delta
tool_start
tool_delta
tool_done
edits
message_done
run_done
error
```

每个 `text_delta` 和工具事件携带 `timelinePartId`，客户端按真实发生顺序增量折叠 timeline，
不暴露内部计划或推理。完整正文和 timeline 只在 `message_done` 发送一次；`edits` 可在工具
完成后提前发布 provisional 预览。`run_done` 只在持久化终态后发布。

HTTP 断开不会自动取消已接受的 run；客户端可带最后事件序号重新订阅。用户显式停止、
后端关闭或不可恢复错误会触发回滚，并产生可观察的终态。

## 验证重点

测试应跨深模块的 interface 断言可观察行为，而不是保留已删除内部规则的单元测试。
关键垂直场景包括：

1. 无工具的自然回答只调用一次模型路径。
2. 模型调用 `web_fetch` 后根据 observation 自然回答，前置文本顺序不丢失。
3. 一个 `edit_execute` 完成复合编辑并产生 pending draft。
4. 字段或目标措辞不会触发运行时预路由。
5. 结构化 `suggestOnly` 拒绝写调用；删除与重排也只能形成需用户确认的 pending preview。
6. 证据或文档合同错误整批回滚。
7. 风格较短、较长或不符合模板化 STAR 的内容不会被在线扫描阻断。
8. 网页抓取结果具有稳定 source ID，但不能支持候选人事实。
9. pending draft 的后续修改沿用 active draft 和原始 base resume。
10. 取消、超限和 provider 错误不留下可应用的 provisional 编辑。
