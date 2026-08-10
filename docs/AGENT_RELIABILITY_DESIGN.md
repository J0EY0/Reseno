# ResuMate Agent 可靠性设计记录

日期：2026-06-21

## 目标

ResuMate Agent 的下一阶段目标不是做通用 Agent 平台，而是在现有简历编辑架构上提升可靠性。Agent 的核心产物是一组可预览、可应用、可撤回的简历草稿修改；自然语言回复负责解释修改，而不是替代结构化编辑。

设计参考 pi-agent 的 runtime、harness、工具契约和事件流思路，但不照搬通用插件系统。所有抽象都应服务“更可靠的简历编辑 Agent”。

## 核心原则

1. 编辑结果可靠性优先  
   所有会改变简历的结果都应落到结构化 `ResumeEditOperation`，并经过统一校验、应用和 observation。

2. 用户确认是最终门槛  
   Agent 只生成 pending draft 或建议，不自动写回正式简历。第一阶段移除或隐藏“低风险自动应用”。

3. 事实不变，表达增强  
   Agent 可以职业化包装已有事实，但不能编造经历、公司、项目、技能、指标、时间、职位或成果。第一阶段通过 prompt 约束事实边界，不做复杂事实校验。

4. Prompt 约束事实，系统硬隔离隐私  
   事实边界先靠 prompt；PII 边界必须由系统保证，包括输入脱敏和写入拒绝。

5. 避免工具膨胀  
   不为每个小需求拆工具。工具数量和 schema token 都会影响模型选择质量。

6. System prompt 单核心维护
   核心系统规则只维护 `system.md` 一份英文版本，避免中英文长 prompt 漂移。语言差异只放在很短的 `system.locale.zh.md` / `system.locale.en.md` 中，用于补充简历表达和用户可见输出风格。

## 隐私边界

姓名、手机、邮箱、地址、头像默认完全隐藏，不进入 LLM payload，也不允许被写入。

Agent 只能看到状态：

```json
{
  "basicFieldStatus": {
    "name": "present",
    "phone": "missing",
    "email": "invalid",
    "location": "present",
    "avatar": "missing"
  }
}
```

`basic.headline` 和 `basic.summary` 属于职业表达，可以读取和编辑；但其中出现的手机号、邮箱等联系方式也需要模式脱敏。

所有读路径都应使用 sanitized resume，包括 prompt payload、`resume_analysis`、`resume_lookup`、`draft_diff_summary`。内部执行 apply 时可以使用真实 draft，但 Tool Guard 必须拒绝 PII path 写入。

GitHub、LinkedIn、作品集等公开链接不按手机/邮箱级别脱敏；但普通请求不自动读取 customFields 中的链接。只有用户本轮明确要求基于该链接作为材料时，才进入 `web_fetch`。

## Task Intent 与编辑 Intent

需要区分两层 intent：

```text
AgentTaskIntent:
- answer_advice
- explain_draft
- research_role
- diagnose_jd_gap
- edit_resume
- rewrite_draft
- analyze_resume
- match_jd

EditPlanIntent:
- rewrite_summary
- rewrite_item
- insert_item
- insert_section
- move_item
- split_item
- merge_items
- classify_skills
- delete_item
- delete_section
- reorder_items
- reorder_sections
```

`AgentTaskIntent` 是后端内部路由策略，不暴露给前端用户协议。前端仍根据事实事件和数据渲染：有没有工具事件、有没有 edits、有没有 message。

`explain_draft` 是顶层只读任务意图，不是 `edit_plan.intent`。它只用于解释 pending draft，必须走 `draft_diff_summary`，不能调用 `edit_plan` 或 `edit_execute`。

`research_role` 是岗位情报只读任务意图。它允许 `web_search` 聚合公开岗位/JD/技能表达参考，但不能调用写工具，也不能把公开信息写成用户个人经历。

`diagnose_jd_gap` 是 JD/岗位差距诊断只读任务意图。它允许读取目标上下文和 `resume_analysis`，输出已匹配内容、缺失关键词、可强化经历和需要用户补充的证据，但不能生成草稿修改。

当用户要求新增或生成经历，但当前简历和本轮输入没有足够真实材料时，Agent 不应生成空泛草稿。第一阶段用 `clarify_only` + `finish(status="blocked", missing=["source_material", "user_evidence"])` 输出一次性证据追问，问题聚焦职责、技术方案、解决的问题和结果/指标。

## Capability Policy 与 Tool Guard

可靠性不只靠 intent classifier，而是三层：

1. `AgentTaskIntent`：用户这轮大概想做什么。
2. `CapabilityPolicy`：系统允许这轮做什么。
3. `Tool Guard`：每次工具执行前的硬拦截。

第一版 policy：

```text
read_only:
  允许 resume_lookup, resume_analysis, draft_diff_summary, finish
  禁止所有写工具

can_draft:
  允许 read tools, edit_plan, edit_execute, finish
  根据明显需求开启 move/split/merge/classify 等专项编辑工具
  禁止 auto apply 和 PII path

can_rewrite_draft:
  需要 pending draft
  允许 draft_diff_summary, draft_rewrite, edit_execute, finish
  禁止从 formal resume 重新生成

clarify_only:
  只允许 finish 或自然语言澄清
```

`suggestOnly` 永远映射为 `read_only` 或 `clarify_only`，不能被用户本轮 prompt 覆盖。

`always` 不等于默认可写。它只表示如果生成草稿，必须等待用户确认；是否可写仍由 task intent 决定。

Tool Guard 第一阶段只硬拦系统边界：

- read-only / suggestOnly 下的写工具。
- rewrite draft 但没有 pending draft。
- PII path 写入。
- 删除或大范围重排缺少明确用户意图。
- `edit_execute` 缺少明确目标字段、sectionId 或 itemId。
- 未注册工具、未知参数、schema 无效。

不硬拦写作质量、STAR 完整度、JD 匹配度或复杂事实校验。

## 工具设计

第一阶段保留现有细粒度编辑工具，不合并进 `edit_execute.action`。

对模型暴露的写工具可以仍包括：

```text
edit_execute
edit_move_item
edit_split_item
edit_merge_items
skills_classify
draft_rewrite
```

但代码层必须收敛为共享执行核心：

```text
write tool -> build edit entries -> validate -> apply -> observations
```

这样既保留细粒度工具对模型的清晰度，又避免写入逻辑分散。

对模型暴露的简历专用读工具保持克制：

```text
resume_analysis
resume_lookup
draft_diff_summary
material_extract
web_fetch
web_search
```

`material_extract` 只整理用户 prompt、会话级 `targetContext`、附件中的候选片段，不做事实校验，也不直接写草稿。`resume_analysis` 输出 `targetFit`，用于表达目标岗位、关键词缺口、建议编辑目标和风险代码。

`ToolSpec` 第一版保持最小，只描述工具元数据；是否允许本轮调用仍由
`CapabilityPolicy` 根据请求上下文判断：

```python
AgentToolSpec(
    name: str,
    schema: dict,
    mode: "read" | "write" | "control",
    handler_name: str,
    requires_pending_draft: bool = False,
)
```

`finish` 属于 control tool，不混入 read tools。暂不做 hooks、插件、
并行策略、动态 handler dispatch 和复杂 streaming callback。

## `edit_plan` 合同

`edit_plan` 不只是展示文案，而是执行前合同。但第一阶段渐进增强，不一次强制所有字段。

第一阶段强制：

```text
intent
target
reason
```

兼容现有 `action`。

第一阶段可选收集：

```text
stepId
riskLevel
evidence
targetContext
expectedOperationTypes
```

后续 replay 覆盖稳定后，再对中高风险操作逐步要求 evidence 和 risk。

`evidence` 和 `targetContext` 分开：

- `evidence`：支持用户确实有这些经历、项目、技能。
- `targetContext`：支持目标岗位希望强调什么。

来源规则：

```text
resume_lookup -> evidence
用户本轮输入 / 附件 -> evidence
web_fetch(project_reference / portfolio_reference, canSupportResumeFacts=true) -> evidence
web_fetch(jd) -> targetContext
web_search -> targetContext
JD -> targetContext
```

第一阶段记录 evidence，不做强事实校验。

## Web 工具

将现有 JD fetch/search 的底层能力抽成更通用的 web 能力，但保留边界：

```text
web_fetch:
  抓取用户本轮明确提供且 purpose 明确的 URL。

web_search:
  只用于 JD、岗位、行业表达参考，不作为用户经历事实来源。
```

`web_search` 可以接收单个 `query`，也可以接收最多 5 个 `queries` 和最多 10 个 `maxResults`。当用户只是想了解某类岗位、行业方向或常见要求时，Agent 应优先用一次 `web_search` 传入 3-5 个互补查询，例如职责、技能要求、简历关键词、行业表达、面试/JD 常见要求，再基于合并后的结果输出自然语言总结。这样减少重复工具调用，也避免把中间可恢复失败暴露给用户。

`web_fetch` 必须声明 `purpose`：

```text
jd
project_reference
portfolio_reference
company_reference
```

未知用途 URL 先确认，不直接抓。

`web_fetch` 抓取失败时，不自动转搜索替代；请用户粘贴内容或换链接。

`web_search` 可以先尝试抓取搜索结果正文；如果结果页不可读，但搜索结果摘要本身足够明确，则可降级使用搜索摘要作为岗位/JD 参考，避免把可恢复的抓取失败暴露成工具失败。

多查询 `web_search` 的输出保留兼容字段 `query`、`url`、`title`、`excerpt`，同时增加 `queries`、`queryCount`、`maxResults` 和 `results`。`results` 只作为 target context，不是用户个人经历证据。

`web_fetch` 输出应包含结构化标记：

```json
{
  "title": "...",
  "url": "...",
  "purpose": "project_reference",
  "excerpt": "...",
  "sourceType": "web",
  "canSupportResumeFacts": true
}
```

用户明确提供的 GitHub repo、作品集项目页、JD URL 可以进入 sources 并展示完整 URL。

## `explain_draft`

`explain_draft` 由自然语言 prompt 触发，不需要 UI 上的“解释”按钮。

必须调用 `draft_diff_summary`，不能从压缩历史里猜。

输出粒度：

- 按 edit/diff 分组。
- 说明改了哪里、为什么改、影响范围。
- 可以给是否建议应用的克制判断。
- 不展示 raw operation JSON、字段路径、tool 参数或内部 intent/action 名称。

`draft_diff_summary` 输出必须包含稳定的 `index` 和 `referenceMap`，用于把“第二条修改”“上一版项目修改”等多轮指代映射到 editId/target。

后续可以继续支持选择参数：

```json
{
  "editId": "edit-xxx",
  "index": 2,
  "query": "项目经历"
}
```

找不到目标时返回 `selectionError`，由模型向用户确认。

无 pending draft 时，不自动分析正式简历，也不生成新草稿；应 `finish(blocked, missing=["pending_draft"])`。

## Event Stream v2

第一版事件集合保持最小：

```text
message_start
message_delta
message_done
tool_start
tool_delta
tool_done
edits
error
```

不单独暴露 `task_intent`、`policy` 或 `plan_*` 事件。前端 timeline 由事件顺序派生。

## Blocked 出口

`finish(status=blocked)` 是澄清出口。第一版增加可选 `missing` 枚举：

```text
pending_draft
draft_edit_target
resume_target
source_material
target_role
user_evidence
url_purpose
explicit_delete_intent
explicit_reorder_intent
model_config
```

## Replay Harness 场景

第一批 replay 场景：

1. `explain_draft_success`  
   pending draft 存在，用户问第二条改了什么，只调用 `draft_diff_summary`，不调用写工具。

2. `explain_draft_no_pending`  
   无 pending draft，返回 `finish(blocked, missing=["pending_draft"])`。

3. `suggest_only_blocks_draft`  
   `suggestOnly` 下用户要求优化，不产生 edits。

4. `pii_hidden_and_write_blocked`  
   payload 和读工具输出不含 name、phone、email、location；写 PII path 被拒。

5. `rewrite_project_with_lookup`  
   项目 bullet 改写必须经过 lookup、plan、execute，生成 pending draft。

6. `explicit_web_fetch_project_reference`
   用户明确给 GitHub repo 并要求基于项目优化，`web_fetch(project_reference)` 可作为 evidence。

7. `material_extract_attachment`
   用户上传/粘贴材料时，`material_extract` 提取脱敏候选片段和建议模块。

8. `material_extract_jd_reference_only`
   JD 中出现技能关键词时仍保持 referenceOnly，不作为可直接写入简历的用户事实。

9. `resume_analysis_target_fit`
   `resume_analysis` 返回 `targetFit`，包含目标角色、关键词计数、建议编辑目标和风险代码。

10. `draft_diff_reference_map`
   pending draft 的 edits/diffs 输出稳定 index/referenceMap，支持多轮定位。

11. `quality_issue_*`
    写工具成功后仍返回非阻断 `qualityIssues`，replay event 记录 `qualityIssueCount`。

12. `customfield_github_not_auto_fetched`
   customFields 有 GitHub URL，但普通优化请求不调用 web_fetch。

13. `unknown_url_purpose_blocked`
   用户只发未知 URL，返回 `blocked(url_purpose)`。

14. `delete_requires_explicit_intent`
   泛泛“优化结构”不能调用 delete 或 reorder。

15. `draft_rewrite_uses_pending_draft`
    继续改刚才草稿时基于 pending draft，不从 formal resume 重来。

## 落地顺序

1. 文档/ADR 固化原则。
2. 实现 PII sanitized resume。
3. 引入 ToolSpec 和 active tools。
4. 接入 AgentTaskIntent、CapabilityPolicy、Tool Guard。
5. 实现 Event Stream v2 和 replay harness。
