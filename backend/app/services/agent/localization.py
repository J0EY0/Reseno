from __future__ import annotations

from typing import Any

from app.agent_locales import (
    DEFAULT_AGENT_LOCALE,
    normalize_agent_locale,
)

TEXT: dict[str, dict[str, str]] = {
    "en": {
        "edit.default.reason": "Create a previewable draft for the current request.",
        "edit.default.title": "Edit {index}",
        "edit.title.add": "Add {label}",
        "edit.title.delete": "Delete {label}",
        "edit.title.reorder": "Reorder {label}",
        "edit.title.update": "Update {label}",
        "edit.label.sections": "resume sections",
        "error.edit_execute_rejected_detailed": (
            "No executable edits were accepted. Check required fields such as "
            "sectionId, itemId, path, patch, and operation type."
        ),
        "error.edit_entry_must_object": "Edit entry must be an object.",
        "error.tool_blocked_suggest_only": (
            "Suggestion-only mode disables draft-editing tools."
        ),
        "error.unknown_tool": "Unknown tool: {name}",
        "error.web_fetch_failed": (
            "The URL could not be fetched. Ask the user to paste the content or "
            "provide another link."
        ),
        "error.web_search_failed": (
            "Web search is temporarily unavailable. Try a narrower query or ask "
            "the user for a relevant URL."
        ),
        "error.context_window_exceeded": (
            "The current resume, attachments, and request do not fit the selected "
            "model context window. Shorten the current input or choose a model "
            "with a larger context window."
        ),
        "model.error.label": "Provider response",
        "model.error.text": (
            'Model config "{name}" was found, but the provider request failed. '
            "Check the API URL, API key, model name, and network access."
        ),
        "model.setup.text": (
            "No usable model configuration is available yet. Add a model, enter "
            "its API key, then ask the agent to analyze or edit the resume."
        ),
        "locale.name": "English",
        "response.model_turn_limit": (
            "The agent reached its model-action limit before it could complete "
            "safely. No unfinished changes were applied; please retry."
        ),
        "diff.field.company": "Company",
        "diff.field.content": "Content",
        "diff.field.authors": "Authors",
        "diff.field.date": "Date",
        "diff.field.degree": "Degree",
        "diff.field.description": "Description",
        "diff.field.gpa": "GPA",
        "diff.field.headline": "Headline",
        "diff.field.highlights": "Highlights",
        "diff.field.issuer": "Issuer",
        "diff.field.location": "Location",
        "diff.field.major": "Major",
        "diff.field.name": "Name",
        "diff.field.period": "Period",
        "diff.field.position": "Position",
        "diff.field.role": "Role",
        "diff.field.school": "School",
        "diff.field.summary": "Summary",
        "diff.field.techStack": "Tech stack",
        "diff.field.title": "Title",
        "diff.field.url": "Link",
        "diff.field.venue": "Venue",
        "diff.kind.achievement": "Achievement",
        "diff.kind.education": "Education",
        "diff.kind.experience": "Experience",
        "diff.kind.project": "Project",
        "diff.kind.publication": "Publication",
        "diff.kind.simple_list": "List",
        "diff.label.item_field": "{kind} {field}",
    },
    "zh": {
        "edit.default.reason": "根据当前请求生成可预览草稿",
        "edit.default.title": "修改建议 {index}",
        "edit.title.add": "新增{label}",
        "edit.title.delete": "删除{label}",
        "edit.title.reorder": "调整{label}顺序",
        "edit.title.update": "更新{label}",
        "edit.label.sections": "简历模块",
        "error.edit_execute_rejected_detailed": (
            "没有可执行的修改被接受。请检查 sectionId、itemId、path、patch "
            "和 operation type 等必填字段"
        ),
        "error.edit_entry_must_object": "修改条目必须是对象",
        "error.tool_blocked_suggest_only": "仅给建议模式下已禁用草稿编辑工具",
        "error.unknown_tool": "未知工具：{name}",
        "error.web_fetch_failed": (
            "无法抓取这个链接。请让用户粘贴内容，或提供另一个可访问链接"
        ),
        "error.web_search_failed": (
            "网页搜索暂时不可用。请缩小查询范围，或让用户提供相关链接"
        ),
        "error.context_window_exceeded": (
            "当前简历、附件和请求无法放入所选模型的上下文窗口。请缩短本次输入，"
            "或选择上下文窗口更大的模型"
        ),
        "model.error.label": "提供方返回",
        "model.error.text": (
            "已找到模型配置「{name}」，但调用模型失败。请检查 API 地址、API Key、"
            "模型名称和网络连通性后重试"
        ),
        "model.setup.text": (
            "当前还没有可用的大模型配置。请先在「大模型配置」中新增模型、填写 "
            "API Key，然后再让 Agent 分析或修改简历"
        ),
        "locale.name": "Chinese",
        "response.model_turn_limit": (
            "Agent 在安全完成前已达到模型操作轮次上限。未完成的修改均未应用，请重试"
        ),
        "diff.field.company": "企业",
        "diff.field.content": "内容",
        "diff.field.authors": "作者",
        "diff.field.date": "日期",
        "diff.field.degree": "学历",
        "diff.field.description": "描述",
        "diff.field.gpa": "GPA",
        "diff.field.headline": "求职方向",
        "diff.field.highlights": "亮点",
        "diff.field.issuer": "颁发机构",
        "diff.field.location": "地点",
        "diff.field.major": "专业",
        "diff.field.name": "名称",
        "diff.field.period": "时间",
        "diff.field.position": "职位",
        "diff.field.role": "角色",
        "diff.field.school": "学校",
        "diff.field.summary": "个人简介",
        "diff.field.techStack": "技术栈",
        "diff.field.title": "标题",
        "diff.field.url": "链接",
        "diff.field.venue": "发表载体",
        "diff.kind.achievement": "成果",
        "diff.kind.education": "教育",
        "diff.kind.experience": "工作",
        "diff.kind.project": "项目",
        "diff.kind.publication": "论文",
        "diff.kind.simple_list": "列表",
        "diff.label.item_field": "{kind}{field}",
    },
}


def agent_text(locale: str, key: str, **values: Any) -> str:
    """Return one localized agent runtime string."""

    safe_locale = normalize_agent_locale(locale)
    bundle = TEXT.get(safe_locale) or TEXT[DEFAULT_AGENT_LOCALE]
    template = bundle.get(key) or TEXT[DEFAULT_AGENT_LOCALE].get(key) or key
    return template.format(**values) if values else template
