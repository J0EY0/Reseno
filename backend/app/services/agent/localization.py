from __future__ import annotations

from typing import Any

from app.agent_locales import (
    DEFAULT_AGENT_LOCALE,
    SUPPORTED_AGENT_LOCALES,
    normalize_agent_locale,
)

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "edit.default.reason": "Create a previewable draft for the current request.",
        "edit.default.title": "Edit {index}",
        "error.draft_rewrite_missing_edits": "draft_rewrite requires non-empty edits.",
        "error.edit_execute_missing_inputs": (
            "Call edit_plan first or provide explicit executable edits."
        ),
        "error.edit_execute_rejected": (
            "No executable edits were accepted. Check sectionId, itemId, patch, "
            "and operation arguments."
        ),
        "error.edit_execute_rejected_detailed": (
            "No executable edits were accepted. Check required fields such as "
            "sectionId, itemId, path, patch, and operation type."
        ),
        "error.edit_repair_required": (
            "The rejected edit batch must be corrected and resent in full "
            "before finish."
        ),
        "error.edit_entry_must_object": "Edit entry must be an object.",
        "error.edit_plan_missing_inputs": (
            "Call resume_analysis first or provide explicit plan steps."
        ),
        "error.jd_url_missing": "Missing JD URL.",
        "error.merge_items_missing_args": (
            "merge_items requires sectionId, at least two itemIds, and mergedItem."
        ),
        "error.merge_items_missing_targets": (
            "merge_items requires existing, distinct itemIds in the target section."
        ),
        "error.move_item_missing_item": (
            "move_item requires an existing itemId in fromSectionId."
        ),
        "error.move_item_missing_sections": (
            "move_item requires existing fromSectionId and toSectionId."
        ),
        "error.skills_classify_empty_groups": (
            "skills_classify requires non-empty groups."
        ),
        "error.skills_classify_empty_items": (
            "skills_classify requires groups with title and skills."
        ),
        "error.split_item_missing_args": (
            "split_item requires sectionId, itemId, first, and second."
        ),
        "error.split_item_missing_target": (
            "split_item requires an existing sectionId and itemId."
        ),
        "error.tool_blocked_by_policy": (
            "This tool is not available for the current agent task."
        ),
        "error.tool_blocked_clarify_only": (
            "This turn needs clarification before tools can modify the resume."
        ),
        "error.tool_blocked_read_only": (
            "This turn is read-only, so draft-editing tools are disabled."
        ),
        "error.tool_blocked_suggest_only": (
            "Suggestion-only mode disables draft-editing tools."
        ),
        "error.tool_requires_pending_draft": (
            "This request needs an existing pending draft first."
        ),
        "error.tool_requires_delete_intent": (
            "Delete operations require an explicit delete request from the user."
        ),
        "error.tool_requires_reorder_intent": (
            "Move or reorder operations require an explicit reorder request."
        ),
        "error.unknown_tool": "Unknown tool: {name}",
        "error.web_fetch_failed": (
            "The URL could not be fetched. Ask the user to paste the content or "
            "provide another link."
        ),
        "error.web_fetch_purpose_required": (
            "web_fetch requires an explicit purpose for the URL."
        ),
        "error.web_fetch_url_missing": "web_fetch requires a user-provided URL.",
        "error.web_search_failed": "web_search did not return usable context.",
        "error.web_search_purpose_required": (
            "web_search requires an explicit reference purpose."
        ),
        "jd.search.fallback_excerpt": (
            "No JD URL was detected. The agent will search a JD reference from "
            "the target role and response language."
        ),
        "jd.search.query": "{role} job description responsibilities requirements",
        "jd.url.fetch_error": "JD URL could not be fetched or parsed.",
        "knowledge.default_detail": (
            "Prepare this as definition, project example, and likely follow-ups."
        ),
        "model.error.label": "Provider response",
        "model.error.text": (
            'Model config "{name}" was found, but the provider request failed. '
            "Check the API URL, API key, model name, and network access."
        ),
        "model.setup.quick_reply": "Configure model",
        "model.setup.text": (
            "No usable model configuration is available yet. Add a model, enter "
            "its API key, then ask the agent to analyze or edit the resume."
        ),
        "locale.name": "English",
        "list.separator": ", ",
        "plan.confirm_target": "Confirm target-role requirements",
        "plan.generate_draft": "Generate a preview draft",
        "plan.locate_sections": "Identify sections to adjust",
        "plan.prepare_export": "Prepare the export result",
        "plan.reason.delete_empty_sections": (
            "Remove empty sections so the resume is easier to scan."
        ),
        "plan.reason.insert_project": (
            "Add a verifiable project section for the target role."
        ),
        "plan.reason.insert_project_empty_resume": (
            "The resume has no editable items yet, so first turn the provided "
            "project content into a previewable section."
        ),
        "plan.reason.reorder_sections": (
            "Move stronger role-fit sections ahead of education."
        ),
        "plan.reason.replace_summary": (
            "The summary should align with the target role and JD keywords."
        ),
        "plan.reason.update_first_item": (
            "The strongest experience needs clearer responsibility, stack, "
            "and outcome."
        ),
        "plan.review_resume": "Review the current resume",
        "plan.summarize": "Summarize the changes",
        "response.blocked.default_reason": "Reason: not enough context.",
        "response.blocked.reason": "Reason: {reason}",
        "response.blocked.text": (
            "I cannot produce a reliable previewable draft yet. {detail} "
            "Provide the target field, section, item, or real experience details "
            "before continuing."
        ),
        "response.blocked.material": (
            "I cannot produce a reliable previewable draft yet because the resume "
            "does not include enough user-provided evidence for this content.\n"
            "Please answer 2-4 of these questions, and I can turn the answers into "
            "resume bullets:\n"
            "- What part did you personally own?\n"
            "- What technologies, methods, or implementation choices did you use?\n"
            "- What problem did this solve, and for whom?\n"
            "- What result, deliverable, metric, or visible impact can be stated?"
        ),
        "response.explain_draft": (
            "I inspected the pending draft changes and summarized what changed. "
            "No new resume edits were created in this explanation turn."
        ),
        "response.edit_transaction_failed": (
            "I couldn't produce a valid draft, so no changes were applied."
        ),
        "response.no_edits": (
            "I completed the tool checks needed for this turn, but did not "
            "produce a safe previewable draft. Tell me which field, section, or "
            "item to modify; if this should be role-matched, provide the target "
            "JD or role."
        ),
        "response.with_edits": (
            "I completed this pass and generated {count} previewable changes. "
            "The preview shows a temporary highlighted draft that you can apply "
            "or discard."
        ),
        "role.default": "frontend engineer",
        "section.awards": "Awards",
        "section.certificates": "Certificates",
        "section.custom": "Custom Section",
        "section.default": "Section",
        "section.education": "Education",
        "section.internship": "Internship Experience",
        "section.languages": "Languages",
        "section.other": "Other",
        "section.project": "Projects",
        "section.skills": "Skills",
        "section.work": "Work Experience",
        "highlight.first_item": (
            "Add role-specific proof for {role}: technical trade-offs, "
            "collaboration scope, and measurable outcome."
        ),
        "structured.reason.classify_skills": (
            "Group skills by category so recruiters can scan them quickly."
        ),
        "structured.reason.merge_items": (
            "Merge duplicate or closely related items to reduce fragmentation."
        ),
        "structured.reason.move_item": "Move the resume item as requested.",
        "structured.reason.split_item": (
            "Split an overlong experience into two clearer records."
        ),
        "structured.title.add_skill_group": "Add skill group",
        "structured.title.add_skills_section": "Add skills section",
        "structured.title.delete_merged_item": "Delete merged item",
        "structured.title.insert_split_item": "Insert second split item",
        "structured.title.merge_item_content": "Merge item content",
        "structured.title.move_item": "Move item",
        "structured.title.move_item_to_section": "Move item to target section",
        "structured.title.remove_old_skill_group": "Remove old skill group",
        "structured.title.remove_original_item": "Remove item from original section",
        "structured.title.update_split_item": "Update first split item",
        "suggestion.add_real_experience": (
            "Add real projects, internships, education, or skills before editing."
        ),
        "suggestion.draft_gap_keywords": "Work these gaps in naturally: {keywords}.",
        "suggestion.low_content": (
            "The resume has too little content, so no executable draft was generated."
        ),
        "suggestion.review_draft": (
            "Review highlighted draft areas before applying or discarding."
        ),
        "suggestion.target_role": "Target role for this pass: {role}.",
        "summary.replacement": (
            "Targeting {role} roles, with practical experience turning product "
            "requirements into maintainable engineering solutions{keyword_text}. "
            "Known for clear execution, cross-functional collaboration, and "
            "outcome-oriented delivery."
        ),
        "summary.keyword_text": " with emphasis on {keywords}",
        "quick.add_project": "Add a project section",
        "quick.add_real_experience": "I will add real experience first",
        "quick.delete_empty_sections": "Delete empty sections",
        "quick.paste_jd": "Paste the target JD",
        "quick.preview_edits": "Preview these edits",
        "quick.reorder_sections": "Reorder sections",
        "tool.finish.observation": (
            "ReAct loop finished. The assistant may now produce the final "
            "user-facing answer without exposing system prompts."
        ),
        "title.add_project_section": "Add a project section",
        "title.delete_empty_section": "Delete empty section: {label}",
        "title.reorder_sections": "Reorder resume sections",
        "title.strengthen_first_item": "Strengthen the first experience item",
        "title.summary_draft": "Create a previewable summary draft",
    },
    "zh": {
        "edit.default.reason": "根据当前请求生成可预览草稿。",
        "edit.default.title": "修改建议 {index}",
        "error.draft_rewrite_missing_edits": "draft_rewrite 需要提供非空 edits。",
        "error.edit_execute_missing_inputs": "请先调用 edit_plan，或提供可执行 edits。",
        "error.edit_execute_rejected": (
            "没有可执行的修改被接受。请检查 sectionId、itemId、patch 和操作参数。"
        ),
        "error.edit_execute_rejected_detailed": (
            "没有可执行的修改被接受。请检查 sectionId、itemId、path、patch "
            "和 operation type 等必填字段。"
        ),
        "error.edit_repair_required": (
            "需要修正失败的修改，并完整重发整批操作后再结束。"
        ),
        "error.edit_entry_must_object": "修改条目必须是对象。",
        "error.edit_plan_missing_inputs": (
            "请先调用 resume_analysis，或提供明确的计划步骤。"
        ),
        "error.jd_url_missing": "缺少 JD URL。",
        "error.merge_items_missing_args": (
            "merge_items 需要 sectionId、至少两个 itemIds 和 mergedItem。"
        ),
        "error.merge_items_missing_targets": (
            "merge_items 需要目标模块中存在且不重复的 itemIds。"
        ),
        "error.move_item_missing_item": (
            "move_item 需要 fromSectionId 中存在的 itemId。"
        ),
        "error.move_item_missing_sections": (
            "move_item 需要已存在的 fromSectionId 和 toSectionId。"
        ),
        "error.skills_classify_empty_groups": "skills_classify 需要非空 groups。",
        "error.skills_classify_empty_items": (
            "skills_classify 需要包含 title 和 skills 的分组。"
        ),
        "error.split_item_missing_args": (
            "split_item 需要 sectionId、itemId、first 和 second。"
        ),
        "error.split_item_missing_target": (
            "split_item 需要已存在的 sectionId 和 itemId。"
        ),
        "error.tool_blocked_by_policy": "当前 Agent 任务不允许调用这个工具。",
        "error.tool_blocked_clarify_only": (
            "本轮需要先澄清信息，不能调用会修改简历的工具。"
        ),
        "error.tool_blocked_read_only": (
            "本轮是只读任务，已禁用草稿编辑工具。"
        ),
        "error.tool_blocked_suggest_only": (
            "仅给建议模式下已禁用草稿编辑工具。"
        ),
        "error.tool_requires_pending_draft": "这个请求需要先有一个待确认草稿。",
        "error.tool_requires_delete_intent": "删除操作需要用户明确提出删除请求。",
        "error.tool_requires_reorder_intent": (
            "移动或排序操作需要用户明确提出调整顺序请求。"
        ),
        "error.unknown_tool": "未知工具：{name}",
        "error.web_fetch_failed": (
            "无法抓取这个链接。请让用户粘贴内容，或提供另一个可访问链接。"
        ),
        "error.web_fetch_purpose_required": "web_fetch 需要明确说明链接用途。",
        "error.web_fetch_url_missing": "web_fetch 需要用户提供 URL。",
        "error.web_search_failed": "web_search 没有返回可用参考内容。",
        "error.web_search_purpose_required": "web_search 需要明确说明搜索用途。",
        "jd.search.fallback_excerpt": (
            "未检测到 JD URL。已尝试按目标岗位和中文语境搜索 JD 参考。"
        ),
        "jd.search.query": "{role} 岗位 JD 职责 任职要求",
        "jd.url.fetch_error": "JD URL 无法获取或解析。",
        "knowledge.default_detail": "准备成“概念解释 + 项目例子 + 常见追问”的结构。",
        "model.error.label": "提供方返回",
        "model.error.text": (
            "已找到模型配置「{name}」，但调用模型失败。请检查 API 地址、API Key、"
            "模型名称和网络连通性后重试。"
        ),
        "model.setup.quick_reply": "去配置模型",
        "model.setup.text": (
            "当前还没有可用的大模型配置。请先在「大模型配置」中新增模型、填写 "
            "API Key，然后再让 Agent 分析或修改简历。"
        ),
        "locale.name": "Chinese",
        "list.separator": "、",
        "plan.confirm_target": "确认目标岗位要求",
        "plan.generate_draft": "生成可预览草稿",
        "plan.locate_sections": "定位需要调整的模块",
        "plan.prepare_export": "准备导出结果",
        "plan.reason.delete_empty_sections": "删除没有可见内容的空模块，减少干扰。",
        "plan.reason.insert_project": "根据目标岗位补充一个可验证的项目模块。",
        "plan.reason.insert_project_empty_resume": (
            "当前简历还没有可编辑条目，先把用户提供的项目内容转成可预览模块。"
        ),
        "plan.reason.reorder_sections": "把更能证明岗位匹配度的模块放在教育信息之前。",
        "plan.reason.replace_summary": "简介需要先对齐目标岗位和 JD 关键词。",
        "plan.reason.update_first_item": "最强经历需要更明确地呈现职责、技术和结果。",
        "plan.review_resume": "检查当前简历内容",
        "plan.summarize": "汇总修改结果",
        "response.blocked.default_reason": "原因：当前信息不足。",
        "response.blocked.reason": "原因：{reason}",
        "response.blocked.text": (
            "我还不能生成可靠的可预览修改草稿。{detail} "
            "请补充目标字段、模块、条目或真实经历后再继续。"
        ),
        "response.blocked.material": (
            "我还不能生成可靠的可预览修改草稿，因为当前简历和本轮输入里缺少"
            "足够的真实经历证据。\n"
            "你可以先回答下面 2-4 个问题，我再把答案整理成简历要点：\n"
            "- 你本人具体负责哪一部分？\n"
            "- 用了哪些技术、方法或实现方案？\n"
            "- 解决了什么问题，面向谁或什么场景？\n"
            "- 有没有结果、交付物、指标或可公开描述的影响？"
        ),
        "response.explain_draft": (
            "我已读取当前待确认草稿的修改差异，并会围绕这些差异进行解释；"
            "本轮不会生成新的简历修改。"
        ),
        "response.edit_transaction_failed": "未能生成有效草稿，本轮未应用任何修改。",
        "response.no_edits": (
            "我已完成本轮需要的工具检查，但没有生成可安全预览的修改草稿。"
            "如果你希望我直接改某个模块，请说明目标字段、模块或条目；如果"
            "需要按岗位匹配，请补充目标 JD 或岗位名称。"
        ),
        "response.with_edits": (
            "我已完成本轮处理，生成了 {count} 处可预览修改。"
            "预览区会先显示临时草稿和高亮位置，确认后可以应用或撤回。"
        ),
        "role.default": "前端开发工程师",
        "section.awards": "获奖经历",
        "section.certificates": "证书",
        "section.custom": "自定义模块",
        "section.default": "模块",
        "section.education": "教育经历",
        "section.internship": "实习经历",
        "section.languages": "语言能力",
        "section.other": "其他经历",
        "section.project": "项目经历",
        "section.skills": "技能",
        "section.work": "工作经历",
        "highlight.first_item": (
            "围绕{role}岗位补充技术取舍、协作边界和可验证结果，"
            "让经历从职责描述升级为能力证明。"
        ),
        "structured.reason.classify_skills": "把技能按类别归组，便于招聘方快速扫描。",
        "structured.reason.merge_items": "合并重复或强相关经历，减少信息分散。",
        "structured.reason.move_item": "根据用户要求移动简历条目。",
        "structured.reason.split_item": "将过长经历拆分为更清晰的两条记录。",
        "structured.title.add_skill_group": "新增技能分组",
        "structured.title.add_skills_section": "新增技能模块",
        "structured.title.delete_merged_item": "删除已合并条目",
        "structured.title.insert_split_item": "新增拆分条目",
        "structured.title.merge_item_content": "合并经历内容",
        "structured.title.move_item": "移动条目",
        "structured.title.move_item_to_section": "移动条目到目标模块",
        "structured.title.remove_old_skill_group": "删除旧技能分组",
        "structured.title.remove_original_item": "移除原位置条目",
        "structured.title.update_split_item": "更新拆分后的原条目",
        "suggestion.add_real_experience": (
            "请先补充真实项目、实习、教育或技能信息，再让 Agent 修改。"
        ),
        "suggestion.draft_gap_keywords": "优先自然补足：{keywords}。",
        "suggestion.low_content": (
            "当前简历内容太少，本轮不会生成可执行草稿，避免凭空编造经历。"
        ),
        "suggestion.review_draft": "先在草稿预览中检查高亮区域，再决定应用或撤回。",
        "suggestion.target_role": "本轮参考岗位：{role}。",
        "summary.replacement": (
            "面向{role}岗位，具备与业务场景结合的项目推进、工程实现和跨模块"
            "协作经验{keyword_text}。能够把需求拆解为可落地方案，并通过清晰"
            "的交付结果证明技术能力。"
        ),
        "summary.keyword_text": "，重点覆盖 {keywords}",
        "quick.add_project": "添加项目经历",
        "quick.add_real_experience": "我先补充真实经历",
        "quick.delete_empty_sections": "删除空模块",
        "quick.paste_jd": "粘贴目标 JD",
        "quick.preview_edits": "预览这些修改",
        "quick.reorder_sections": "调整模块顺序",
        "tool.finish.observation": (
            "ReAct 循环已结束。助手现在可以生成最终用户可见回复，且不暴露系统提示词。"
        ),
        "title.add_project_section": "新增项目经历模块",
        "title.delete_empty_section": "删除空模块：{label}",
        "title.reorder_sections": "调整模块顺序",
        "title.strengthen_first_item": "补强首个经历条目",
        "title.summary_draft": "生成可预览的个人简介草稿",
    },
}

SECTION_LABEL_KEYS = {
    "awards",
    "certificates",
    "custom",
    "education",
    "internship",
    "languages",
    "other",
    "project",
    "skills",
    "work",
}


def agent_text(locale: str, key: str, **values: Any) -> str:
    """Return one localized agent runtime string."""

    safe_locale = normalize_agent_locale(locale)
    bundle = TEXT.get(safe_locale) or TEXT[DEFAULT_AGENT_LOCALE]
    template = bundle.get(key) or TEXT[DEFAULT_AGENT_LOCALE].get(key) or key
    return template.format(**values) if values else template


def supported_agent_text_locales() -> tuple[str, ...]:
    """Return locales expected to exist in the agent localization table."""

    return SUPPORTED_AGENT_LOCALES


def section_label(kind: object, locale: str) -> str:
    """Return a localized section label from a stable section kind."""

    key = str(kind)
    if key in SECTION_LABEL_KEYS:
        return agent_text(locale, f"section.{key}")

    return agent_text(locale, "section.default")
