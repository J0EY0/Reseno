import re
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentAction,
    AgentChatMessage,
    AgentChatRequest,
    AgentKnowledgeItem,
    AgentResumeEditSuggestion,
    AgentSource,
    AgentToolInvocation,
)

from .editing import _string_list
from .integrations import JD_URL_PATTERN, WebReference, WebSearchResult, _compact_text
from .localization import agent_text, section_label
from .models import EditPlanStep, JobReference, ResumeAnalysis


def _current_prompt(request: AgentChatRequest) -> str:
    """Return the current user message while keeping the legacy prompt field."""

    if request.message and request.message.text.strip():
        return request.message.text.strip()

    if request.prompt.strip():
        return request.prompt.strip()

    if request.messages:
        last_user = next(
            (
                message.text.strip()
                for message in reversed(request.messages)
                if message.role == "user" and message.text.strip()
            ),
            "",
        )

        if last_user:
            return last_user

    return ""


def _conversation_depth(request: AgentChatRequest) -> int:
    """Return the number of real conversation messages sent by the frontend."""

    if request.messages:
        return len(request.messages)

    return len(request.conversation)


def _active_resume(request: AgentChatRequest) -> dict[str, Any]:
    """Return the resume state tools should inspect for this request."""

    draft = request.draft_state
    if draft and draft.status == "pending" and draft.resume:
        return draft.resume

    return request.resume


def _file_content_excerpt(file: dict[str, Any]) -> str:
    """Return text content supplied with a user attachment."""

    content = file.get("content")
    return _compact_text(content) if isinstance(content, str) else ""


def _agent_file_context(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build the text-only attachment context sent to the model."""

    file_context: list[dict[str, str]] = []
    for file in files:
        excerpt = _file_content_excerpt(file)
        if not excerpt:
            continue

        filename = file.get("filename")
        media_type = file.get("mediaType")
        file_context.append(
            {
                "filename": str(filename or "Attachment"),
                "mediaType": str(media_type or ""),
                "excerpt": excerpt,
            },
        )

    return file_context


def _visible_plan_steps(request: AgentChatRequest) -> list[str]:
    """Return a short, user-facing plan before the ReAct tool loop starts."""

    prompt = _current_prompt(request).lower()
    has_jd_context = bool(
        request.job_brief.strip()
        or JD_URL_PATTERN.search(prompt)
        or "jd" in prompt
        or "岗位" in prompt
        or "job" in prompt
        or "role" in prompt
    )
    asks_export = "pdf" in prompt or "导出" in prompt or "export" in prompt

    steps = [agent_text(request.locale, "plan.review_resume")]
    if has_jd_context:
        steps.append(agent_text(request.locale, "plan.confirm_target"))
    steps.extend(
        [
            agent_text(request.locale, "plan.locate_sections"),
            agent_text(request.locale, "plan.generate_draft"),
        ],
    )
    if asks_export:
        steps.append(agent_text(request.locale, "plan.prepare_export"))
    else:
        steps.append(agent_text(request.locale, "plan.summarize"))
    return steps[:5]


def _has_item_content(item: object) -> bool:
    """Return whether a resume item contains visible content."""

    if not isinstance(item, dict):
        return False

    for key in ("title", "subtitle", "meta", "period", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True

    highlights = item.get("highlights")
    return isinstance(highlights, list) and any(
        isinstance(entry, str) and entry.strip() for entry in highlights
    )


def _section_label(section: dict[str, object], locale: str) -> str:
    """Return a readable section label for response text and edit cards."""

    custom_title = section.get("customTitle")
    if isinstance(custom_title, str) and custom_title.strip():
        return custom_title.strip()

    return section_label(section.get("kind"), locale)


class AgentPlanExecutor:
    """Build resume draft-editing responses and tool payloads."""

    def __init__(self, request: AgentChatRequest) -> None:
        self.request = request
        self.resume = _active_resume(request)
        self.is_zh = request.locale == "zh"
        self.prompt = _current_prompt(request)

    def build_message_from_parts(
        self,
        *,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tools: list[AgentToolInvocation],
        message_id: str | None = None,
        finish_status: str = "",
        finish_reason: str = "",
    ) -> AgentChatMessage:
        """Assemble the final assistant payload from executed tool outputs."""

        sources = self.build_sources(job_reference, analysis)
        knowledge = self.build_knowledge(job_reference, analysis)

        return AgentChatMessage(
            id=message_id or f"agent-msg-{uuid4().hex[:12]}",
            role="assistant",
            tone="success" if edits else "default",
            text=self.build_response_text(
                job_reference,
                analysis,
                plan,
                edits,
                finish_status=finish_status,
                finish_reason=finish_reason,
            ),
            plan=_visible_plan_steps(self.request),
            suggestions=self.build_suggestions(job_reference, analysis),
            knowledge=knowledge,
            tools=tools,
            sources=sources,
            edits=edits,
            quickReplies=self.build_quick_replies(edits),
            actions=self.build_actions(edits),
        )

    def jd_search_query(self, role: str) -> str:
        """Build the deterministic JD search query for the inferred role."""

        return agent_text(self.request.locale, "jd.search.query", role=role)

    def build_url_job_reference_from_web(
        self,
        url: str,
        role: str,
        web_reference: WebReference | None,
    ) -> JobReference:
        """Convert an optional fetched JD URL result into agent context."""

        excerpt = (
            web_reference.excerpt
            if web_reference
            else self.request.job_brief.strip()[:260]
            or self.prompt.replace(url, "").strip()[:260]
        )
        return JobReference(
            mode="url",
            role=role,
            query="",
            url=url,
            excerpt=excerpt,
            source_title=web_reference.title if web_reference else "",
            source_excerpt=web_reference.excerpt if web_reference else "",
            tool_state="output-available" if web_reference else "output-error",
            tool_error=None
            if web_reference
            else agent_text(self.request.locale, "jd.url.fetch_error"),
            result_count=1 if web_reference else 0,
        )

    def build_search_job_reference_from_result(
        self,
        role: str,
        query: str,
        search_result: WebSearchResult | None,
        result_count: int,
        search_error: str | None,
    ) -> JobReference:
        """Convert an optional JD search result into agent context."""

        fallback_excerpt = agent_text(self.request.locale, "jd.search.fallback_excerpt")

        if search_result:
            excerpt = search_result.excerpt
            source_title = search_result.title
            source_url = search_result.url
            source_excerpt = search_result.excerpt if not search_error else ""
        else:
            excerpt = fallback_excerpt
            source_title = ""
            source_url = None
            source_excerpt = ""

        return JobReference(
            mode="search",
            role=role,
            query=query,
            url=source_url,
            excerpt=excerpt,
            source_title=source_title,
            source_excerpt=source_excerpt,
            tool_state="output-error" if search_error else "output-available",
            tool_error=search_error,
            result_count=result_count,
        )

    def infer_target_role(self) -> str:
        """Infer the target role from JD text, user prompt, or resume headline."""

        context = f"{self.request.job_brief}\n{self.prompt}".strip()
        role_patterns = (
            self.zh_role_patterns() if self.is_zh else self.en_role_patterns()
        )

        for pattern in role_patterns:
            match = re.search(pattern, context, flags=re.IGNORECASE)
            if match:
                role = self.clean_inferred_role(match.group(1))
                if role:
                    return role

        basic = self.resume.get("basic")
        if isinstance(basic, dict):
            headline = basic.get("headline")
            if isinstance(headline, str) and headline.strip():
                return headline.strip()[:40]

        return agent_text(self.request.locale, "role.default")

    def zh_role_patterns(self) -> list[str]:
        """Return conservative Chinese patterns for explicit target roles."""

        return [
            (
                r"(?:应聘|目标|投递|申请)(?:的)?(?:岗位|职位)?"
                r"(?:是|为|:|：|\s)+([^\n，。,.；;]{2,40})"
            ),
            r"(?:岗位|职位)(?:是|为|:|：|\s)+([^\n，。,.；;]{2,40})",
            r"(?:应聘|投递|申请)([^\n，。,.；;]{2,40}?)(?:岗位|职位)",
        ]

    def en_role_patterns(self) -> list[str]:
        """Return conservative English patterns for explicit target roles."""

        return [
            (
                r"(?:target\s+)?(?:role|position)\s*"
                r"(?:is|as|:|-)?\s+([^\n,.]{2,40})"
            ),
            r"(?:applying|apply)\s+(?:for|to)\s+(?:a|an|the)?\s*([^\n,.]{2,40})",
            (
                r"(frontend|backend|full[- ]?stack|data|machine learning|product)"
                r"\s+engineer"
            ),
        ]

    def clean_inferred_role(self, value: str) -> str:
        """Remove connective words that are not part of the target role."""

        role = value.strip()
        role = re.sub(r"^(?:的)?(?:岗位|职位)?(?:是|为|:|：|\s)+", "", role)
        role = re.sub(r"^(?:role|position)\s+(?:is|as)\s+", "", role, flags=re.I)
        role = re.split(
            r"(?:\s+请|\s+帮我|\s+优化|\s+修改|\s+调整|，|。|,|；|;)",
            role,
            maxsplit=1,
        )[0]
        return role.strip()[:40]

    def analyze_resume(self) -> ResumeAnalysis:
        """Extract only the resume facts needed for planning."""

        basic = self.resume.get("basic")
        basic_data = basic if isinstance(basic, dict) else {}
        sections_value = self.resume.get("sections")
        sections = sections_value if isinstance(sections_value, list) else []
        normalized_sections: list[dict[str, object]] = []
        empty_section_ids: list[str] = []

        for section in sections:
            if not isinstance(section, dict):
                continue

            section_id = section.get("id")
            if not isinstance(section_id, str) or not section_id:
                continue

            normalized_sections.append(section)
            items = section.get("items")
            visible_items = (
                [item for item in items if _has_item_content(item)]
                if isinstance(items, list)
                else []
            )

            if not visible_items:
                empty_section_ids.append(section_id)

        title = "resume"
        for key in ("name", "headline"):
            value = basic_data.get(key)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                break

        summary_value = basic_data.get("summary")
        summary = summary_value.strip() if isinstance(summary_value, str) else ""

        return ResumeAnalysis(
            title=title,
            summary=summary,
            sections=normalized_sections,
            empty_section_ids=empty_section_ids,
            matched_keywords=_string_list(
                self.request.keyword_match.get("matched"),
            )[:6],
            missing_keywords=_string_list(
                self.request.keyword_match.get("missing"),
            )[:6],
        )

    def create_plan(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[EditPlanStep]:
        """Create readable, conservative plan steps from user intent."""

        prompt = self.prompt.lower()
        wants_add = bool(
            re.search(r"新增|添加|补充|add|insert|create|项目|project", prompt),
        )
        wants_delete = bool(
            re.search(r"删除|移除|去掉|delete|remove", prompt),
        )
        wants_reorder = bool(
            re.search(r"顺序|排序|前置|调整模块|reorder|order|move", prompt),
        )
        wants_summary = bool(
            re.search(r"简介|summary|概述|profile|优化|润色|rewrite", prompt),
        )
        wants_bullet = bool(
            re.search(r"经历|项目|bullet|量化|impact|experience", prompt),
        )
        plan: list[EditPlanStep] = []

        if not self.has_editable_resume_content(analysis):
            if wants_add or wants_bullet:
                reason = agent_text(
                    self.request.locale,
                    "plan.reason.insert_project_empty_resume",
                )
                plan.append(EditPlanStep("insert_project", "sections", reason))
            return plan

        if wants_summary:
            reason = agent_text(
                self.request.locale,
                "plan.reason.replace_summary",
            )
            plan.append(EditPlanStep("replace_summary", "basic.summary", reason))

        if wants_bullet and self.find_first_item_section(analysis):
            reason = agent_text(
                self.request.locale,
                "plan.reason.update_first_item",
            )
            plan.append(EditPlanStep("update_first_item", "sections.items", reason))

        if wants_add or (wants_bullet and not self.find_project_section(analysis)):
            reason = agent_text(
                self.request.locale,
                "plan.reason.insert_project",
            )
            plan.append(EditPlanStep("insert_project", "sections", reason))

        if wants_reorder and len(analysis.sections) > 1:
            reason = agent_text(
                self.request.locale,
                "plan.reason.reorder_sections",
            )
            plan.append(EditPlanStep("reorder_sections", "sections", reason))

        if wants_delete and analysis.empty_section_ids:
            reason = agent_text(
                self.request.locale,
                "plan.reason.delete_empty_sections",
            )
            plan.append(EditPlanStep("delete_empty_sections", "sections", reason))

        return plan

    def has_editable_resume_content(self, analysis: ResumeAnalysis) -> bool:
        """Return whether the resume has enough facts for executable edits."""

        if analysis.summary:
            return True

        return self.find_first_item_section(analysis) is not None

    def execute_plan(
        self,
        plan: list[EditPlanStep],
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentResumeEditSuggestion]:
        """Translate plan steps into frontend-executable draft operations."""

        edits: list[AgentResumeEditSuggestion] = []

        for step in plan:
            if step.action in {"replace_summary", "replace_field"}:
                edits.append(self.build_summary_edit(step, job_reference, analysis))
                continue

            if step.action in {"update_first_item", "update_item"}:
                edit = self.build_first_item_edit(step, job_reference, analysis)
                if edit:
                    edits.append(edit)
                continue

            if step.action in {"insert_project", "insert_section", "insert_item"}:
                edits.append(self.build_project_section_edit(step, job_reference))
                continue

            if step.action == "reorder_sections":
                edit = self.build_reorder_sections_edit(step, analysis)
                if edit:
                    edits.append(edit)
                continue

            if step.action == "delete_empty_sections":
                edits.extend(self.build_delete_empty_section_edits(step, analysis))

        return edits

    def build_summary_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion:
        """Build the summary replacement operation."""

        keywords = analysis.missing_keywords[:3] or analysis.matched_keywords[:3]
        keyword_text = ""
        if keywords:
            keyword_text = agent_text(
                self.request.locale,
                "summary.keyword_text",
                keywords=agent_text(self.request.locale, "list.separator").join(
                    keywords,
                ),
            )
        replacement = agent_text(
            self.request.locale,
            "summary.replacement",
            role=job_reference.role,
            keyword_text=keyword_text,
        )
        title = agent_text(self.request.locale, "title.summary_draft")

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target=step.target,
            reason=step.reason,
            replacement=replacement,
            operation={
                "type": "replace_field",
                "path": "basic.summary",
                "value": replacement,
            },
            status="executed",
        )

    def build_first_item_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion | None:
        """Build an update operation for the first meaningful resume item."""

        section = self.find_first_item_section(analysis)
        if not section:
            return None

        items = section.get("items")
        item = (
            next(
                (
                    entry
                    for entry in items
                    if isinstance(entry, dict) and _has_item_content(entry)
                ),
                None,
            )
            if isinstance(items, list)
            else None
        )
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None

        current_highlights = _string_list(item.get("highlights"))
        new_highlight = agent_text(
            self.request.locale,
            "highlight.first_item",
            role=job_reference.role,
        )
        title = agent_text(self.request.locale, "title.strengthen_first_item")

        section_id = str(section["id"])
        item_id = str(item["id"])
        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target=f"sections.{section_id}.items.{item_id}",
            reason=step.reason,
            replacement=new_highlight,
            operation={
                "type": "update_item",
                "sectionId": section_id,
                "itemId": item_id,
                "patch": {
                    "highlights": [*current_highlights, new_highlight],
                },
            },
            status="executed",
        )

    def build_project_section_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
    ) -> AgentResumeEditSuggestion:
        """Build an insert operation for a new project section."""

        section_id = f"section-agent-project-{uuid4().hex[:8]}"
        item_id = f"item-agent-project-{uuid4().hex[:8]}"
        prompt_project = self.extract_project_from_prompt()

        title = agent_text(self.request.locale, "title.add_project_section")
        section_title = section_label("project", self.request.locale)
        project_title = prompt_project["title"]
        description = prompt_project["description"]
        highlights = prompt_project["highlights"]

        section = {
            "id": section_id,
            "kind": "project",
            "layout": "timeline",
            "customTitle": "",
            "items": [
                {
                    "id": item_id,
                    "title": project_title,
                    "subtitle": prompt_project["subtitle"],
                    "meta": prompt_project["meta"],
                    "period": prompt_project["period"],
                    "description": description,
                    "highlights": highlights,
                },
            ],
        }

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target="sections",
            reason=step.reason,
            replacement=section_title,
            operation={
                "type": "insert_section",
                "section": section,
                "index": self.find_project_insert_index(),
            },
            status="executed",
        )

    def extract_project_from_prompt(self) -> dict[str, Any]:
        """Extract a conservative project item from user-provided prompt text."""

        text = _compact_text(self.prompt, limit=900)
        title = ""
        subtitle = ""
        meta = ""
        period = ""

        def labeled_value(labels: str, stop_labels: str, limit: int = 80) -> str:
            pattern = rf"(?:{labels})[:：]\s*(.+?)(?=\s*(?:{stop_labels})[:：]|\n|$)"
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" ，。；;,")[:limit]
            return ""

        stop_labels = (
            r"项目名称|项目名|项目|时间|日期|周期|角色|职位|岗位|技术栈|技术|"
            r"背景|描述|简介|工作内容|职责|负责|结果|成果|影响|"
            r"project(?:\s+name)?|time|date|period|role|position|tech stack|"
            r"stack|description|context|responsibility|action|result|impact"
        )
        title = labeled_value(
            r"项目名称|项目名|project(?:\s+name)?",
            stop_labels,
            60,
        )
        if not title:
            title = labeled_value(r"项目|project", stop_labels, 60)
        subtitle = labeled_value(r"角色|职位|岗位|role|position", stop_labels, 60)
        meta = labeled_value(r"技术栈|技术|tech stack|stack", stop_labels, 120)

        period_match = re.search(
            r"((?:20\d{2})[./-]\d{1,2}\s*(?:-|–|—|至|到)\s*(?:20\d{2})?[./-]?\d{0,2})",
            text,
        )
        if period_match:
            period = period_match.group(1).strip()
        else:
            period = labeled_value(r"时间|日期|周期|time|date|period", stop_labels, 60)

        cleaned = re.sub(
            r"^(?:帮我|请|麻烦)?(?:修改|优化|润色|新增|添加|补充|生成)?"
            r"(?:我的|这段|以下)?(?:简历|项目经历|项目)?[:：,，\s]*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        description = labeled_value(
            r"背景|描述|简介|description|context",
            stop_labels,
            120,
        )

        parts = [
            re.sub(
                r"^(?:工作内容|职责|负责内容|行动|方案|结果|成果|影响|要点|"
                r"responsibility|action|solution|result|impact|highlight)"
                r"[:：]\s*",
                "",
                part.strip(" -•\t"),
                flags=re.IGNORECASE,
            )
            for part in re.split(r"[。；;\n]+", cleaned)
            if part.strip(" -•\t")
        ]
        field_values = [title, subtitle, meta, period, description]
        field_keys = {
            re.sub(r"[\s:：,，.。;；\-–—/、·]+", "", value).lower()
            for value in field_values
            if value
        }
        field_label_pattern = re.compile(
            r"^(?:项目名称|项目名|项目|时间|日期|周期|角色|职位|岗位|技术栈|技术|"
            r"背景|描述|简介|project(?:\s+name)?|time|date|period|role|"
            r"position|tech stack|stack|description|context)[:：]",
            flags=re.IGNORECASE,
        )
        highlights: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if not part:
                continue
            if field_label_pattern.search(part):
                responsibility_match = re.search(
                    r"(?:工作内容|职责|负责内容|responsibility|action)[:：]\s*(.+)"
                    r"|(?:^|\s)(负责\s+.+)$",
                    part,
                    flags=re.IGNORECASE,
                )
                if not responsibility_match:
                    continue
                part = (
                    responsibility_match.group(1)
                    or responsibility_match.group(2)
                    or ""
                ).strip()
            if not part:
                continue
            key = re.sub(r"[\s:：,，.。;；\-–—/、·]+", "", part).lower()
            if not key or key in seen or key in field_keys:
                continue
            repeated_field_count = sum(
                field_key in key for field_key in field_keys if len(field_key) >= 3
            )
            if repeated_field_count >= 2:
                continue
            highlights.append(part)
            seen.add(key)
            if len(highlights) >= 3:
                break

        return {
            "title": title,
            "subtitle": subtitle,
            "meta": meta,
            "period": period,
            "description": description,
            "highlights": highlights,
        }

    def build_reorder_sections_edit(
        self,
        step: EditPlanStep,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion | None:
        """Build an operation that reorders existing sections."""

        if len(analysis.sections) < 2:
            return None

        priority = {
            "work": 0,
            "internship": 1,
            "project": 2,
            "skills": 3,
            "awards": 4,
            "certificates": 5,
            "languages": 6,
            "custom": 7,
            "other": 8,
            "education": 9,
        }
        ordered_sections = sorted(
            analysis.sections,
            key=lambda section: priority.get(str(section.get("kind")), 9),
        )
        ordered_ids = [
            str(section["id"])
            for section in ordered_sections
            if isinstance(section.get("id"), str)
        ]

        if ordered_ids == [str(section["id"]) for section in analysis.sections]:
            return None

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=agent_text(self.request.locale, "title.reorder_sections"),
            target="sections",
            reason=step.reason,
            replacement=", ".join(ordered_ids),
            operation={
                "type": "reorder_sections",
                "sectionIds": ordered_ids,
            },
            status="executed",
        )

    def build_delete_empty_section_edits(
        self,
        step: EditPlanStep,
        analysis: ResumeAnalysis,
    ) -> list[AgentResumeEditSuggestion]:
        """Build delete operations for sections without visible content."""

        edits: list[AgentResumeEditSuggestion] = []
        sections_by_id = {
            str(section["id"]): section
            for section in analysis.sections
            if isinstance(section.get("id"), str)
        }

        for section_id in analysis.empty_section_ids:
            section = sections_by_id.get(section_id)
            if not section:
                continue

            label = _section_label(section, self.request.locale)
            edits.append(
                AgentResumeEditSuggestion(
                    id=f"edit-{uuid4().hex[:8]}",
                    title=agent_text(
                        self.request.locale,
                        "title.delete_empty_section",
                        label=label,
                    ),
                    target=f"sections.{section_id}",
                    reason=step.reason,
                    replacement=None,
                    operation={
                        "type": "delete_section",
                        "sectionId": section_id,
                    },
                    status="executed",
                ),
            )

        return edits

    def build_tools(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tool_ids: dict[str, str] | None = None,
    ) -> list[AgentToolInvocation]:
        """Return tool call metadata for the deterministic fallback phases."""

        tool_ids = tool_ids or {}
        tools = [
            self.build_jd_tool(job_reference, tool_ids.get("jd")),
            self.build_resume_analysis_tool(analysis, tool_ids.get("analysis")),
        ]

        tools.append(self.build_plan_tool(plan, tool_ids.get("plan")))

        if plan:
            tools.append(
                self.build_execute_tool(plan, edits, tool_ids.get("execute")),
            )

        return tools

    def build_jd_tool(
        self,
        job_reference: JobReference,
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed JD fetch/search tool invocation."""

        jd_tool_type = (
            "tool-jd_url_fetch"
            if job_reference.mode == "url"
            else "tool-jd_reference_search"
        )
        jd_input = (
            {"url": job_reference.url}
            if job_reference.mode == "url"
            else {"query": job_reference.query, "language": self.request.locale}
        )
        jd_output = {
            "mode": job_reference.mode,
            "role": job_reference.role,
            "excerpt": job_reference.excerpt,
            "resultCount": job_reference.result_count,
        }
        if job_reference.url:
            jd_output["url"] = job_reference.url

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type=jd_tool_type,
            title=(
                "jd_url_fetch" if job_reference.mode == "url" else "jd_reference_search"
            ),
            state=job_reference.tool_state,
            input=jd_input,
            output=jd_output,
            errorText=job_reference.tool_error,
        )

    def build_resume_analysis_tool(
        self,
        analysis: ResumeAnalysis,
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed local resume analysis tool invocation."""

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-resume_analysis",
            title="resume_analysis",
            state="output-available",
            input={
                "resumeTitle": analysis.title,
                "sectionCount": len(analysis.sections),
                "conversationDepth": _conversation_depth(self.request),
            },
            output={
                "missingKeywords": analysis.missing_keywords,
                "matchedKeywords": analysis.matched_keywords,
                "emptySectionIds": analysis.empty_section_ids,
            },
        )

    def build_plan_tool(
        self,
        plan: list[EditPlanStep],
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed edit planning tool invocation."""

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-edit_plan",
            title="edit_plan",
            state="output-available",
            input={"stepCount": len(plan)},
            output=[
                {
                    "action": step.action,
                    "target": step.target,
                    "reason": step.reason,
                }
                for step in plan
            ],
        )

    def build_execute_tool(
        self,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tool_id: str | None = None,
        *,
        observations: list[dict[str, Any]] | None = None,
        rejected_edits: list[dict[str, Any]] | None = None,
    ) -> AgentToolInvocation:
        """Return the completed draft edit execution tool invocation."""

        output: dict[str, Any] = {
            "editCount": len(edits),
            "operationTypes": [
                edit.operation.get("type") for edit in edits if edit.operation
            ],
            "observations": observations or [],
        }
        if rejected_edits:
            output["rejectedEditCount"] = len(rejected_edits)
            output["rejectedEdits"] = rejected_edits

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-edit_execute",
            title="edit_execute",
            state="output-available",
            input={"planStepCount": len(plan)},
            output=output,
        )

    def build_sources(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentSource]:
        """Build citation metadata only from user-visible external content."""

        sources: list[AgentSource] = []

        if job_reference.source_excerpt:
            source_id = (
                "source-jd-url" if job_reference.mode == "url" else "source-jd-search"
            )
            sources.append(
                AgentSource(
                    id=source_id,
                    title=job_reference.source_title or "Target JD URL",
                    sourceType="web",
                    url=job_reference.url,
                    excerpt=job_reference.source_excerpt,
                ),
            )

        if self.request.job_brief.strip():
            sources.append(
                AgentSource(
                    id="source-job-brief",
                    title="Target job description",
                    sourceType="jobBrief",
                    excerpt=self.request.job_brief.strip()[:220],
                ),
            )

        for index, file in enumerate(self.request.files[:3], start=1):
            excerpt = _file_content_excerpt(file)
            if not excerpt:
                continue

            filename = file.get("filename")
            sources.append(
                AgentSource(
                    id=f"source-attachment-{index}",
                    title=str(filename or f"Attachment {index}"),
                    sourceType="attachment",
                    url=file.get("url") if isinstance(file.get("url"), str) else None,
                    excerpt=excerpt,
                ),
            )

        return sources

    def build_suggestions(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[str]:
        """Build short guidance text next to executable edits."""

        if not self.has_editable_resume_content(analysis):
            return [
                agent_text(self.request.locale, "suggestion.low_content"),
                agent_text(self.request.locale, "suggestion.add_real_experience"),
                agent_text(
                    self.request.locale,
                    "suggestion.target_role",
                    role=job_reference.role,
                ),
            ]

        suggestions = [
            agent_text(self.request.locale, "suggestion.review_draft"),
            agent_text(
                self.request.locale,
                "suggestion.target_role",
                role=job_reference.role,
            ),
        ]
        if analysis.missing_keywords:
            suggestions.append(
                agent_text(
                    self.request.locale,
                    "suggestion.draft_gap_keywords",
                    keywords=agent_text(self.request.locale, "list.separator").join(
                        analysis.missing_keywords[:3],
                    ),
                ),
            )

        return suggestions[:3]

    def build_knowledge(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentKnowledgeItem]:
        """Build knowledge preparation entries from role and keyword gaps."""

        terms = analysis.missing_keywords[:3] or analysis.matched_keywords[:2]
        if not terms:
            terms = [job_reference.role]

        detail = agent_text(self.request.locale, "knowledge.default_detail")

        return [AgentKnowledgeItem(title=term, detail=detail) for term in terms]

    def build_quick_replies(
        self,
        edits: list[AgentResumeEditSuggestion],
    ) -> list[str]:
        """Return quick replies that keep draft editing moving."""

        if not edits:
            return [
                agent_text(self.request.locale, "quick.add_real_experience"),
                agent_text(self.request.locale, "quick.paste_jd"),
                agent_text(self.request.locale, "quick.add_project"),
            ]

        return [
            agent_text(self.request.locale, "quick.preview_edits"),
            agent_text(self.request.locale, "quick.reorder_sections"),
            agent_text(self.request.locale, "quick.delete_empty_sections"),
            agent_text(self.request.locale, "quick.add_project"),
        ]

    def build_actions(
        self,
        edits: list[AgentResumeEditSuggestion],
    ) -> list[AgentAction]:
        """Return only actions that are valid for the generated response."""

        if edits:
            return ["plan", "execute", "summary", "bullet", "keywords"]

        return ["summary", "keywords"]

    def build_response_text(
        self,
        _job_reference: JobReference,
        _analysis: ResumeAnalysis,
        _plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        *,
        finish_status: str = "",
        finish_reason: str = "",
    ) -> str:
        """Build the assistant message body shown in the conversation."""

        if finish_status == "blocked":
            reason = finish_reason.strip()
            reason_key = (
                "response.blocked.reason"
                if reason
                else "response.blocked.default_reason"
            )
            detail = agent_text(
                self.request.locale,
                reason_key,
                reason=reason,
            )
            return agent_text(
                self.request.locale,
                "response.blocked.text",
                detail=detail,
            )

        if not edits:
            return agent_text(self.request.locale, "response.no_edits")

        return agent_text(
            self.request.locale,
            "response.with_edits",
            count=len(edits),
        )

    def find_project_section(
        self, analysis: ResumeAnalysis
    ) -> dict[str, object] | None:
        """Return the first project section, if present."""

        return next(
            (
                section
                for section in analysis.sections
                if section.get("kind") == "project"
            ),
            None,
        )

    def find_first_item_section(
        self,
        analysis: ResumeAnalysis,
    ) -> dict[str, object] | None:
        """Return the first section with at least one visible item."""

        for section in analysis.sections:
            items = section.get("items")
            if isinstance(items, list) and any(
                _has_item_content(item) for item in items
            ):
                return section

        return None

    def find_project_insert_index(self) -> int:
        """Choose a predictable insertion point for generated project sections."""

        sections_value = self.resume.get("sections")
        sections = sections_value if isinstance(sections_value, list) else []

        for index, section in enumerate(sections):
            if isinstance(section, dict) and section.get("kind") == "education":
                return index

        return len(sections)
