import re
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentAction,
    AgentChatMessage,
    AgentChatRequest,
    AgentFinishMissing,
    AgentKnowledgeItem,
    AgentResumeEditSuggestion,
    AgentSource,
    AgentToolInvocation,
)

from .attachments import attachment_text, current_request_attachments
from .editing import _string_list
from .integrations import URL_PATTERN, WebReference, WebSearchResult, _compact_text
from .localization import agent_text, section_label
from .models import (
    EditPlanStep,
    ResumeAnalysis,
    TargetOpportunityKind,
    TargetReference,
    TargetReferenceSource,
)
from .parsing_patterns import agent_pattern, agent_patterns, matches_agent_pattern
from .policy import AgentTaskIntent, infer_agent_task_intent
from .privacy import resume_hidden_terms, sanitize_agent_resume, sanitize_agent_text

OPPORTUNITY_KIND_PATTERN_KEYS: tuple[
    tuple[TargetOpportunityKind, str],
    ...,
] = (
    ("scholarship", "target.kind.scholarship"),
    ("graduate_study", "target.kind.graduate_study"),
    ("research", "target.kind.research"),
    ("employment", "target.kind.employment"),
)


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


def _file_content_text(
    session_id: str,
    file: dict[str, Any],
    *,
    hidden_terms: tuple[str, ...] = (),
) -> str:
    """Return bounded attachment text suitable for model context."""

    content = attachment_text(session_id, file)
    if not content:
        return ""
    return sanitize_agent_text(content, hidden_terms=hidden_terms).strip()


def _agent_file_context(
    session_id: str,
    files: list[dict[str, Any]],
    *,
    hidden_terms: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Build the text-only attachment context sent to the model."""

    file_context: list[dict[str, str]] = []
    for file in files:
        excerpt = _file_content_text(
            session_id,
            file,
            hidden_terms=hidden_terms,
        )
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
        or URL_PATTERN.search(prompt)
        or matches_agent_pattern(prompt, "visible_plan.job_context")
    )
    asks_export = matches_agent_pattern(prompt, "visible_plan.export")

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
        # `jobBrief` remains the request wire name; normalize it at this boundary.
        self.target_brief = request.job_brief.strip()
        self.resume = _active_resume(request)
        self.hidden_terms = resume_hidden_terms(self.resume)
        self.visible_resume = sanitize_agent_resume(
            self.resume,
            hidden_terms=self.hidden_terms,
        )
        self.is_zh = request.locale == "zh"
        self.prompt = _current_prompt(request)

    def build_message_from_parts(
        self,
        *,
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tools: list[AgentToolInvocation],
        message_id: str | None = None,
        finish_status: str = "",
        finish_reason: str = "",
        finish_missing: list[AgentFinishMissing] | None = None,
    ) -> AgentChatMessage:
        """Assemble the final assistant payload from executed tool outputs."""

        sources = self.build_sources(target_reference, analysis)
        knowledge = self.build_knowledge(target_reference, analysis)

        return AgentChatMessage(
            id=message_id or f"agent-msg-{uuid4().hex[:12]}",
            role="assistant",
            tone="success" if edits else "default",
            text=self.build_response_text(
                target_reference,
                analysis,
                plan,
                edits,
                finish_status=finish_status,
                finish_reason=finish_reason,
                finish_missing=finish_missing or [],
            ),
            plan=_visible_plan_steps(self.request),
            suggestions=self.build_suggestions(target_reference, analysis),
            knowledge=knowledge,
            tools=tools,
            sources=sources,
            edits=edits,
            finishMissing=finish_missing or [],
            quickReplies=self.build_quick_replies(edits),
            actions=self.build_actions(edits),
        )

    def infer_target_kind(self, context: str = "") -> TargetOpportunityKind:
        """Classify the target into the small set supported by the resume agent."""

        text = f"{self.target_brief}\n{context or self.prompt}".casefold()
        if matches_agent_pattern(
            text,
            "target.exact_job_description",
            locale="all",
        ):
            return "employment"

        for kind, pattern_key in OPPORTUNITY_KIND_PATTERN_KEYS:
            if matches_agent_pattern(text, pattern_key, locale="all"):
                return kind

        # Existing `jobBrief` clients historically use the field for a JD.
        return "employment" if self.target_brief else "general"

    def has_exact_job_description(
        self,
        kind: TargetOpportunityKind | None = None,
    ) -> bool:
        """Return whether the compatibility brief represents an exact JD."""

        resolved_kind = kind or self.infer_target_kind()
        if resolved_kind != "employment":
            return False
        if self.target_brief:
            return True
        return matches_agent_pattern(
            self.prompt,
            "target.exact_job_description",
            locale="all",
        )

    def infer_target(self, kind: TargetOpportunityKind | None = None) -> str:
        """Infer a compact opportunity label without forcing a job role."""

        resolved_kind = kind or self.infer_target_kind()
        if resolved_kind == "employment":
            return self.infer_target_role()

        context = self.target_brief or self.prompt
        first_line = next(
            (line.strip() for line in context.splitlines() if line.strip()),
            "",
        )
        compact = " ".join(first_line.split()).strip()
        if compact:
            return compact[:80]

        return agent_text(
            self.request.locale,
            f"target.default.{resolved_kind}",
        )

    def target_reference_from_request(self) -> TargetReference:
        """Normalize the compatibility request field into internal target context."""

        kind = self.infer_target_kind()
        return TargetReference(
            mode="provided" if self.target_brief else "none",
            kind=kind,
            target=self.infer_target(kind),
            query="",
            url=None,
            excerpt=sanitize_agent_text(
                self.target_brief,
                hidden_terms=self.hidden_terms,
            ),
            exact_job_description=self.has_exact_job_description(kind),
        )

    def target_search_query(
        self,
        target: str,
        kind: TargetOpportunityKind,
        *,
        exact_job_description: bool = False,
    ) -> str:
        """Build a deterministic search query for one target opportunity."""

        if exact_job_description:
            return agent_text(self.request.locale, "jd.search.query", role=target)

        suffix = agent_text(
            self.request.locale,
            f"target.search_suffix.{kind}",
        )
        return f"{target} {suffix}".strip()

    def jd_search_query(self, role: str) -> str:
        """Preserve the exact-JD query contract for legacy callers."""

        return self.target_search_query(
            role,
            "employment",
            exact_job_description=True,
        )

    def build_url_target_reference_from_web(
        self,
        url: str,
        target: str,
        web_reference: WebReference | None,
        *,
        kind: TargetOpportunityKind,
        exact_job_description: bool,
    ) -> TargetReference:
        """Convert an optional fetched opportunity page into agent context."""

        excerpt = (
            web_reference.excerpt
            if web_reference
            else self.target_brief[:260] or self.prompt.replace(url, "").strip()[:260]
        )
        source_excerpt = web_reference.excerpt if web_reference else ""
        source = (
            TargetReferenceSource(
                title=sanitize_agent_text(
                    web_reference.title,
                    hidden_terms=self.hidden_terms,
                ),
                url=url,
                excerpt=sanitize_agent_text(
                    source_excerpt,
                    hidden_terms=self.hidden_terms,
                ),
            )
            if web_reference and source_excerpt
            else None
        )
        return TargetReference(
            mode="url",
            kind=kind,
            target=target,
            query="",
            url=url,
            excerpt=sanitize_agent_text(excerpt, hidden_terms=self.hidden_terms),
            exact_job_description=exact_job_description,
            source_title=sanitize_agent_text(
                web_reference.title if web_reference else "",
                hidden_terms=self.hidden_terms,
            ),
            source_excerpt=sanitize_agent_text(
                source_excerpt,
                hidden_terms=self.hidden_terms,
            ),
            sources=(source,) if source else (),
            tool_state="output-available" if web_reference else "output-error",
            tool_error=None
            if web_reference
            else (
                agent_text(self.request.locale, "jd.url.fetch_error")
                if exact_job_description
                else self.target_reference_error_text()
            ),
            result_count=1 if web_reference else 0,
        )

    def build_search_target_reference_from_result(
        self,
        target: str,
        query: str,
        search_result: WebSearchResult | None,
        result_count: int,
        search_error: str | None,
        *,
        kind: TargetOpportunityKind,
        exact_job_description: bool,
        search_results: (
            tuple[WebSearchResult, ...] | list[WebSearchResult] | None
        ) = None,
    ) -> TargetReference:
        """Convert an optional opportunity search result into agent context."""

        fallback_excerpt = (
            agent_text(self.request.locale, "jd.search.fallback_excerpt")
            if exact_job_description
            else self.target_reference_error_text()
        )

        result_sources = tuple(search_results or ())
        if not result_sources and search_result:
            result_sources = (search_result,)

        # Search context may aggregate several excerpts for the model, but each
        # citation keeps only the text obtained from its own URL.
        source_items: list[TargetReferenceSource] = []
        seen_source_urls: set[str] = set()
        if not search_error:
            for result in result_sources:
                if not result.excerpt or result.url in seen_source_urls:
                    continue
                seen_source_urls.add(result.url)
                source_items.append(
                    TargetReferenceSource(
                        title=sanitize_agent_text(
                            result.title,
                            hidden_terms=self.hidden_terms,
                        ),
                        url=result.url,
                        excerpt=sanitize_agent_text(
                            result.excerpt,
                            hidden_terms=self.hidden_terms,
                        ),
                    ),
                )
        sources = tuple(source_items)

        if sources:
            excerpt = _compact_text(" ".join(source.excerpt for source in sources))
            source_title = sources[0].title
            source_url = sources[0].url
            source_excerpt = sources[0].excerpt
        else:
            excerpt = fallback_excerpt
            source_title = ""
            source_url = None
            source_excerpt = ""

        return TargetReference(
            mode="search",
            kind=kind,
            target=target,
            query=query,
            url=source_url,
            excerpt=sanitize_agent_text(excerpt, hidden_terms=self.hidden_terms),
            exact_job_description=exact_job_description,
            source_title=sanitize_agent_text(
                source_title,
                hidden_terms=self.hidden_terms,
            ),
            source_excerpt=sanitize_agent_text(
                source_excerpt,
                hidden_terms=self.hidden_terms,
            ),
            sources=sources,
            tool_state="output-error" if search_error else "output-available",
            tool_error=search_error,
            result_count=result_count,
        )

    def target_reference_error_text(self) -> str:
        """Return a neutral fallback for unavailable opportunity context."""

        return agent_text(
            self.request.locale,
            "target.error.not_found",
        )

    def infer_target_role(self) -> str:
        """Infer the target role from JD text, user prompt, or resume headline."""

        context = f"{self.target_brief}\n{self.prompt}".strip()
        role_patterns = (
            self.zh_role_patterns() if self.is_zh else self.en_role_patterns()
        )

        for pattern in role_patterns:
            match = re.search(pattern, context, flags=re.IGNORECASE)
            if match:
                role = self.clean_inferred_role(match.group(1))
                if role:
                    return role

        basic = self.visible_resume.get("basic")
        if isinstance(basic, dict):
            headline = basic.get("headline")
            if isinstance(headline, str) and headline.strip():
                return headline.strip()[:40]

        return agent_text(self.request.locale, "role.default")

    def zh_role_patterns(self) -> list[str]:
        """Return conservative Chinese patterns for explicit target roles."""

        return list(agent_patterns("role.explicit", locale="zh"))

    def en_role_patterns(self) -> list[str]:
        """Return conservative English patterns for explicit target roles."""

        return list(agent_patterns("role.explicit", locale="en"))

    def clean_inferred_role(self, value: str) -> str:
        """Remove connective words that are not part of the target role."""

        role = value.strip()
        role = re.sub(agent_pattern("role.cleanup_prefix"), "", role, flags=re.I)
        role = re.split(
            agent_pattern("role.trailing_context"),
            role,
            maxsplit=1,
        )[0]
        return role.strip()[:40]

    def analyze_resume(self) -> ResumeAnalysis:
        """Extract only the resume facts needed for planning."""

        basic = self.visible_resume.get("basic")
        basic_data = basic if isinstance(basic, dict) else {}
        sections_value = self.visible_resume.get("sections")
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
        headline = basic_data.get("headline")
        if isinstance(headline, str) and headline.strip():
            title = headline.strip()

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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
    ) -> list[EditPlanStep]:
        """Create readable, conservative plan steps from user intent."""

        prompt = self.prompt.lower()
        wants_add = matches_agent_pattern(prompt, "plan.add")
        wants_delete = matches_agent_pattern(prompt, "plan.delete")
        wants_reorder = matches_agent_pattern(prompt, "plan.reorder")
        wants_summary = matches_agent_pattern(prompt, "plan.summary")
        wants_bullet = matches_agent_pattern(prompt, "plan.bullet")
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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentResumeEditSuggestion]:
        """Translate plan steps into frontend-executable draft operations."""

        edits: list[AgentResumeEditSuggestion] = []

        for step in plan:
            if step.action in {"replace_summary", "replace_field"}:
                edits.append(self.build_summary_edit(step, target_reference, analysis))
                continue

            if step.action in {"update_first_item", "update_item"}:
                edit = self.build_first_item_edit(step, target_reference, analysis)
                if edit:
                    edits.append(edit)
                continue

            if step.action in {"insert_project", "insert_section", "insert_item"}:
                edits.append(self.build_project_section_edit(step, target_reference))
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
        target_reference: TargetReference,
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
            role=target_reference.target,
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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion | None:
        """Build an update operation for the first meaningful resume item."""

        section = next(
            (
                candidate
                for candidate in analysis.sections
                if candidate.get("layout") == "timeline"
                and isinstance(candidate.get("items"), list)
                and any(_has_item_content(item) for item in candidate["items"])
            ),
            None,
        )
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
            role=target_reference.target,
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
        target_reference: TargetReference,
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

        stop_labels = agent_pattern("project.stop_labels")
        title = labeled_value(
            agent_pattern("project.title_labels"),
            stop_labels,
            60,
        )
        if not title:
            title = labeled_value(
                agent_pattern("project.fallback_title_labels"),
                stop_labels,
                60,
            )
        subtitle = labeled_value(
            agent_pattern("project.subtitle_labels"),
            stop_labels,
            60,
        )
        meta = labeled_value(agent_pattern("project.meta_labels"), stop_labels, 120)

        period_match = re.search(
            agent_pattern("project.period_range"),
            text,
        )
        if period_match:
            period = period_match.group(1).strip()
        else:
            period = labeled_value(
                agent_pattern("project.period_labels"),
                stop_labels,
                60,
            )

        cleaned = re.sub(
            agent_pattern("project.request_prefix"),
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()
        description = labeled_value(
            agent_pattern("project.description_labels"),
            stop_labels,
            120,
        )

        parts = [
            re.sub(
                agent_pattern("project.content_label_prefix"),
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
            agent_pattern("project.field_label_prefix"),
            flags=re.IGNORECASE,
        )
        highlights: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if not part:
                continue
            if field_label_pattern.search(part):
                responsibility_match = re.search(
                    agent_pattern("project.responsibility_value"),
                    part,
                    flags=re.IGNORECASE,
                )
                if not responsibility_match:
                    continue
                part = (
                    responsibility_match.group(1) or responsibility_match.group(2) or ""
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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tool_ids: dict[str, str] | None = None,
    ) -> list[AgentToolInvocation]:
        """Return tool call metadata for the deterministic fallback phases."""

        tool_ids = tool_ids or {}
        tools = [
            self.build_target_reference_tool(
                target_reference,
                tool_ids.get("jd"),
            ),
            self.build_resume_analysis_tool(analysis, tool_ids.get("analysis")),
        ]

        tools.append(self.build_plan_tool(plan, tool_ids.get("plan")))

        if plan:
            tools.append(
                self.build_execute_tool(plan, edits, tool_ids.get("execute")),
            )

        return tools

    def build_target_reference_tool(
        self,
        target_reference: TargetReference,
        tool_id: str | None = None,
        tool_name: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed opportunity fetch/search tool invocation."""

        default_tool_name = (
            "web_fetch" if target_reference.mode == "url" else "web_search"
        )
        resolved_tool_name = tool_name or default_tool_name
        tool_type = f"tool-{resolved_tool_name}"
        tool_input = (
            {"url": target_reference.url}
            if target_reference.mode == "url"
            else {"query": target_reference.query, "language": self.request.locale}
        )
        purpose = "jd" if target_reference.exact_job_description else "target_context"
        tool_input["purpose"] = purpose
        primary_source = (
            target_reference.sources[0] if target_reference.sources else None
        )
        tool_output = {
            "mode": target_reference.mode,
            "opportunityType": target_reference.kind,
            "target": target_reference.target,
            # Compatibility fields must describe one source only. Aggregated
            # context stays in TargetReference.excerpt; callers use `results`
            # when they need every source.
            "excerpt": (
                primary_source.excerpt if primary_source else target_reference.excerpt
            ),
            "resultCount": target_reference.result_count,
        }
        if primary_source and primary_source.title:
            tool_output["title"] = primary_source.title
        if target_reference.exact_job_description:
            # Exact-JD consumers still read the historical `role` output key.
            tool_output["role"] = target_reference.target
        if target_reference.url:
            tool_output["url"] = target_reference.url
        if target_reference.sources:
            tool_output["results"] = [
                {
                    "url": source.url,
                    "title": source.title,
                    "excerpt": source.excerpt,
                }
                for source in target_reference.sources
            ]

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type=tool_type,
            title=resolved_tool_name,
            state=target_reference.tool_state,
            input=tool_input,
            output=tool_output,
            errorText=target_reference.tool_error,
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
                "targetFit": self.build_target_fit_summary(analysis),
            },
        )

    def build_target_fit_summary(
        self,
        analysis: ResumeAnalysis,
    ) -> dict[str, Any]:
        """Return structured target-opportunity fit hints for resume planning."""

        has_target_context = bool(
            self.request.job_brief.strip()
            or analysis.matched_keywords
            or analysis.missing_keywords
            or matches_agent_pattern(self.prompt, "visible_plan.job_context")
        )
        warnings: list[str] = []
        if not has_target_context:
            warnings.append("missing_target_context")
        if analysis.missing_keywords:
            warnings.append("missing_keywords_require_user_evidence")
        if not self.has_editable_resume_content(analysis):
            warnings.append("empty_resume_limits_matching")

        kind = self.infer_target_kind()
        target = self.infer_target(kind)
        return {
            "hasTargetContext": has_target_context,
            "opportunityType": kind,
            "targetOpportunity": target,
            # Keep the response key used by existing employment clients.
            "targetRole": target if kind == "employment" else "",
            "score": self.keyword_match_score(),
            "matchedKeywordCount": len(analysis.matched_keywords),
            "missingKeywordCount": len(analysis.missing_keywords),
            "recommendedTargets": self.target_fit_edit_targets(analysis),
            "warnings": warnings,
        }

    def keyword_match_score(self) -> int | float | None:
        """Return a bounded keyword match score from request state."""

        score = self.request.keyword_match.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            return None
        return min(100, max(0, score))

    def target_fit_edit_targets(
        self,
        analysis: ResumeAnalysis,
    ) -> list[dict[str, str]]:
        """Return stable edit targets likely useful for role matching."""

        if not analysis.missing_keywords:
            return []

        targets: list[dict[str, str]] = []
        if analysis.summary:
            targets.append(
                {
                    "target": "basic.summary",
                    "reason": "summary_keyword_alignment",
                },
            )

        item_target = self.first_visible_item_target(analysis)
        if item_target:
            targets.append(
                {
                    "target": item_target,
                    "reason": "experience_keyword_evidence",
                },
            )

        return targets[:2]

    def first_visible_item_target(self, analysis: ResumeAnalysis) -> str:
        """Return the first visible item target path, if one exists."""

        section = self.find_first_item_section(analysis)
        section_id = section.get("id") if section else None
        items = section.get("items") if section else None
        if not isinstance(section_id, str) or not isinstance(items, list):
            return ""

        for item in items:
            if (
                isinstance(item, dict)
                and isinstance(item.get("id"), str)
                and _has_item_content(item)
            ):
                return f"sections.{section_id}.items.{item['id']}"

        return ""

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
        quality_issues: list[dict[str, Any]] | None = None,
        rejected_edits: list[dict[str, Any]] | None = None,
    ) -> AgentToolInvocation:
        """Return the completed draft edit execution tool invocation."""

        issues = quality_issues or []
        output: dict[str, Any] = {
            "editCount": len(edits),
            "operationTypes": [
                edit.operation.get("type") for edit in edits if edit.operation
            ],
            "observations": observations or [],
            "qualityIssueCount": len(issues),
            "qualityIssues": issues,
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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentSource]:
        """Build citation metadata only from user-visible external content."""

        sources: list[AgentSource] = []

        reference_sources = target_reference.sources
        if not reference_sources and target_reference.source_excerpt:
            reference_sources = (
                TargetReferenceSource(
                    title=target_reference.source_title,
                    url=target_reference.url,
                    excerpt=target_reference.source_excerpt,
                ),
            )

        seen_urls: set[str] = set()
        for reference_source in reference_sources:
            if reference_source.url and reference_source.url in seen_urls:
                continue
            if reference_source.url:
                seen_urls.add(reference_source.url)

            source_id_prefix = (
                "source-jd-url"
                if target_reference.mode == "url"
                else "source-jd-search"
            )
            source_id = (
                source_id_prefix
                if not sources
                else f"{source_id_prefix}-{len(sources) + 1}"
            )
            fallback_title = agent_text(
                self.request.locale,
                "target.source.reference",
            )
            sources.append(
                AgentSource(
                    id=source_id,
                    title=reference_source.title or fallback_title,
                    sourceType="web",
                    url=reference_source.url,
                    excerpt=reference_source.excerpt,
                ),
            )

        if self.target_brief:
            sources.append(
                AgentSource(
                    id="source-job-brief",
                    title=agent_text(
                        self.request.locale,
                        "target.source.context",
                    ),
                    sourceType="jobBrief",
                    excerpt=self.target_brief[:220],
                ),
            )

        for index, file in enumerate(
            current_request_attachments(self.request),
            start=1,
        ):
            filename = file.get("filename")
            sources.append(
                AgentSource(
                    id=f"source-attachment-{index}",
                    title=str(filename or f"Attachment {index}"),
                    sourceType="attachment",
                    url=file.get("url") if isinstance(file.get("url"), str) else None,
                ),
            )

        return sources

    def build_suggestions(
        self,
        target_reference: TargetReference,
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
                    role=target_reference.target,
                ),
            ]

        suggestions = [
            agent_text(self.request.locale, "suggestion.review_draft"),
            agent_text(
                self.request.locale,
                "suggestion.target_role",
                role=target_reference.target,
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
        target_reference: TargetReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentKnowledgeItem]:
        """Build knowledge preparation entries from role and keyword gaps."""

        terms = analysis.missing_keywords[:3] or analysis.matched_keywords[:2]
        if not terms:
            terms = [target_reference.target]

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
        _target_reference: TargetReference,
        _analysis: ResumeAnalysis,
        _plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        *,
        finish_status: str = "",
        finish_reason: str = "",
        finish_missing: list[AgentFinishMissing] | None = None,
    ) -> str:
        """Build the assistant message body shown in the conversation."""

        if finish_status == "blocked":
            missing = finish_missing or []
            if any(value in {"source_material", "user_evidence"} for value in missing):
                return agent_text(self.request.locale, "response.blocked.material")

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

        if (
            not edits
            and infer_agent_task_intent(self.request) == AgentTaskIntent.EXPLAIN_DRAFT
        ):
            return agent_text(self.request.locale, "response.explain_draft")

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
