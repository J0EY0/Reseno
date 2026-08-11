from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion

from .policy import has_explicit_reorder_intent
from .section_registry import SECTION_REGISTRY

_BASIC_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "headline": ("headline", "求职标题", "职业标题", "个人标题"),
    "summary": ("summary", "个人简介", "自我介绍", "职业概述"),
}
_ITEM_IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "education": ("school",),
    "experience": ("company", "position"),
    "project": ("name", "role", "techStack"),
    "achievement": ("name", "issuer"),
    "simple_list": (),
}
_BULLET_TERMS = ("bullet", "bullets", "要点", "亮点", "成果点")
_TECH_STACK_TERMS = ("tech stack", "techstack", "技术栈")
_DESCRIPTION_TERMS = ("项目描述", "经历描述", "工作描述", "description")
_ITEM_FIELD_TERMS: dict[str, tuple[str, ...]] = {
    "company": ("公司", "企业名称", "company"),
    "position": ("职位", "职务", "岗位名称", "position"),
    "school": ("学校", "院校", "school", "university"),
    "degree": ("学位", "学历", "degree"),
    "major": ("专业", "major"),
    "gpa": ("绩点", "gpa"),
    "location": ("地点", "所在地", "location"),
    "period": ("时间", "日期", "起止时间", "period"),
    "date": ("时间", "日期", "date"),
    "name": ("项目名称", "成果名称", "奖项名称", "project name"),
    "role": ("项目角色", "角色", "project role"),
    "issuer": ("颁发方", "颁发机构", "主办方", "issuer"),
    "url": ("链接", "网址", "url"),
    "content": ("技能内容", "列表内容", "skill content"),
    "title": ("模块标题", "章节标题", "section title"),
}
_WHOLE_RESUME_TERMS = (
    "整份简历",
    "整个简历",
    "全部简历",
    "全局简历",
    "whole resume",
    "entire resume",
)
_GENERIC_RESUME_TERMS = ("简历", "resume")
_UNRESOLVED_SCOPE_TERMS = (
    "第一段",
    "第二段",
    "上一段",
    "下一段",
    "上面那条",
    "下面那条",
    "最近一份",
    "第一份",
    "最后一份",
    "first paragraph",
    "previous item",
    "next item",
    "most recent",
)
_EXCLUSIVE_SCOPE_TERMS = ("只", "仅", "only", "just")
_RESTORE_DRAFT_TERMS = ("撤回", "恢复", "还原", "undo", "restore", "revert")
_PENDING_RELATIVE_ITEM_PATTERN = re.compile(
    r"(?:刚才|上次|之前|previous|last).{0,16}"
    r"(?:第?[一二三四五六七八九十\d]+条|bullet|要点|亮点)",
    flags=re.IGNORECASE,
)
_ROLE_MARKER_PATTERN = re.compile(
    r"前端开发实习生|后端开发实习生|开发实习生|前端|后端|客户端|"
    r"开发|工程师|实习生|实习|负责人|经理|developer|engineer|intern",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class EditAuthorization:
    """Prompt-derived targets that one Agent turn may mutate.

    Empty field sets mean every writable field at that exact scope. More
    specific item scopes take precedence over their section/kind scopes.
    """

    allow_all: bool
    allow_section_reorder: bool
    basic_fields: frozenset[str]
    kind_fields: tuple[tuple[str, frozenset[str]], ...]
    section_fields: tuple[tuple[str, frozenset[str]], ...]
    item_fields: tuple[tuple[str, str, frozenset[str]], ...]

    def rejection_reason(
        self,
        operation: dict[str, Any],
        resume: dict[str, Any],
    ) -> str | None:
        """Return why an operation is outside this turn's authorized scope."""

        if self.allow_all:
            return None

        operation_type = _string_value(operation.get("type"))
        if operation_type == "replace_field":
            path = _string_value(operation.get("path"))
            field = path.removeprefix("basic.") if path.startswith("basic.") else ""
            if field and field in self.basic_fields:
                return None
            return _outside_scope(path or operation_type)

        if operation_type == "insert_section":
            section = operation.get("section")
            section_id = (
                _string_value(section.get("id")) if isinstance(section, dict) else ""
            )
            kind = (
                _string_value(section.get("kind")) if isinstance(section, dict) else ""
            )
            if self._section_allows(
                section_id,
                kind,
                _section_item_fields(section),
            ):
                return None
            return _outside_scope(section_id or kind or operation_type)

        if operation_type == "reorder_sections":
            return None if self.allow_section_reorder else _outside_scope("sections")

        section_id = _string_value(operation.get("sectionId"))
        section_kind = _section_kind(resume, section_id)
        if operation_type == "update_section":
            if self._section_allows(
                section_id,
                section_kind,
                _item_fields(operation.get("patch")),
            ):
                return None
            return _outside_scope(f"sections.{section_id}")

        if operation_type in {"delete_section", "reorder_items"}:
            if self._section_allows_structure(section_id, section_kind):
                return None
            return _outside_scope(f"sections.{section_id}")

        if operation_type == "insert_item":
            item = operation.get("item")
            item_id = _string_value(item.get("id")) if isinstance(item, dict) else ""
            if self._item_allows(
                section_id,
                item_id,
                section_kind,
                _item_fields(item),
            ):
                return None
            return _outside_scope(f"sections.{section_id}.items.{item_id}")

        if operation_type == "update_item":
            item_id = _string_value(operation.get("itemId"))
            fields = _item_fields(operation.get("patch"))
            if self._item_allows(section_id, item_id, section_kind, fields):
                return None
            return _outside_scope(f"sections.{section_id}.items.{item_id}")

        if operation_type == "delete_item":
            item_id = _string_value(operation.get("itemId"))
            if self._item_allows_structure(section_id, item_id, section_kind):
                return None
            return _outside_scope(f"sections.{section_id}.items.{item_id}")

        return _outside_scope(operation_type or "unknown operation")

    def plan_target_rejection_reason(
        self,
        entry: dict[str, Any],
        resume: dict[str, Any],
    ) -> str | None:
        """Authorize a metadata-only plan step before it can be cached."""

        if self.allow_all or isinstance(entry.get("operation"), dict):
            return None

        target = _string_value(entry.get("target"))
        action = _string_value(entry.get("action")).casefold()
        if target.startswith("basic."):
            field = target.removeprefix("basic.").split(".", maxsplit=1)[0]
            return None if field in self.basic_fields else _outside_scope(target)

        parts = target.split(".")
        if len(parts) >= 4 and parts[0] == "sections" and parts[2] == "items":
            section_id, item_id = parts[1], parts[3]
            section_kind = _section_kind(resume, section_id)
            if self._item_allows(section_id, item_id, section_kind, frozenset()):
                return None
            return _outside_scope(target)

        if len(parts) >= 2 and parts[0] == "sections" and parts[1]:
            section_id = parts[1]
            section_kind = _section_kind(resume, section_id)
            if self._section_allows(section_id, section_kind, frozenset()):
                return None
            return _outside_scope(target)

        if (
            target == "sections"
            and action in {"insert_section", "insert_project"}
            and len(self.kind_fields) == 1
        ):
            return None
        if (
            target == "sections"
            and action == "reorder_sections"
            and self.allow_section_reorder
        ):
            return None
        return _outside_scope(target or action or "plan step")

    def _kind_allows(self, kind: str, fields: frozenset[str]) -> bool:
        for allowed_kind, allowed_fields in self.kind_fields:
            if allowed_kind == kind and _fields_allow(allowed_fields, fields):
                return True
        return False

    def _section_allows(
        self,
        section_id: str,
        section_kind: str,
        fields: frozenset[str],
    ) -> bool:
        for allowed_section_id, allowed_fields in self.section_fields:
            if allowed_section_id == section_id and _fields_allow(
                allowed_fields,
                fields,
            ):
                return True
        return self._kind_allows(section_kind, fields)

    def _section_allows_structure(self, section_id: str, section_kind: str) -> bool:
        if any(
            allowed_section_id == section_id and not allowed_fields
            for allowed_section_id, allowed_fields in self.section_fields
        ):
            return True
        return any(
            allowed_kind == section_kind and not allowed_fields
            for allowed_kind, allowed_fields in self.kind_fields
        )

    def _item_allows(
        self,
        section_id: str,
        item_id: str,
        section_kind: str,
        fields: frozenset[str],
    ) -> bool:
        for allowed_section_id, allowed_item_id, allowed_fields in self.item_fields:
            if (
                allowed_section_id == section_id
                and allowed_item_id == item_id
                and _fields_allow(allowed_fields, fields)
            ):
                return True
        return self._section_allows(section_id, section_kind, fields)

    def _item_allows_structure(
        self,
        section_id: str,
        item_id: str,
        section_kind: str,
    ) -> bool:
        if any(
            allowed_section_id == section_id
            and allowed_item_id == item_id
            and not allowed_fields
            for allowed_section_id, allowed_item_id, allowed_fields in self.item_fields
        ):
            return True
        return self._section_allows_structure(section_id, section_kind)


def derive_edit_authorization(
    request: AgentChatRequest,
    resume: dict[str, Any],
) -> EditAuthorization:
    """Derive the only resume targets writable during the current user turn."""

    prompt = request.message.text.strip()
    restores_pending_draft = bool(
        request.draft_state
        and request.draft_state.status == "pending"
        and any(_contains_term(prompt, term) for term in _RESTORE_DRAFT_TERMS)
    )
    has_unresolved_scope = any(
        _contains_term(prompt, term) for term in _UNRESOLVED_SCOPE_TERMS
    )
    has_resume_target = any(
        _contains_term(prompt, term)
        for term in (*_WHOLE_RESUME_TERMS, *_GENERIC_RESUME_TERMS)
    )
    requested_fields = _requested_item_fields(prompt)
    basic_fields = {
        field
        for field, terms in _BASIC_FIELD_TERMS.items()
        if any(_contains_term(prompt, term) for term in terms)
    }
    if re.search(r"(?<!项目)(?<!经历)(?<!公司)简介", prompt):
        basic_fields.add("summary")
    mentioned_kinds = {
        section["kind"]
        for section in SECTION_REGISTRY
        if any(_contains_term(prompt, alias) for alias in section["aliases"])
    }
    if "project" in mentioned_kinds and re.search(r"项目(?:名称|经历|经验)", prompt):
        has_experience_scope = re.search(
            r"实习|工作经历|工作经验|internship|work experience",
            prompt,
            re.I,
        )
        if not has_experience_scope:
            mentioned_kinds.discard("experience")
        has_skills_scope = re.search(
            r"(?:整理|修改|优化|分类|归类).{0,8}技能|技能(?:模块|分组|经历)",
            prompt,
        )
        if not has_skills_scope:
            mentioned_kinds.discard("simple_list")

    section_fields: dict[str, frozenset[str]] = {}
    item_fields: dict[tuple[str, str], frozenset[str]] = {}
    item_kinds: set[str] = set()
    sections = _resume_sections(resume)
    for section in sections:
        section_id = _string_value(section.get("id"))
        section_kind = _string_value(section.get("kind"))
        title = _string_value(section.get("title"))
        if section_id and title and _contains_term(prompt, title):
            section_fields[section_id] = requested_fields

        for item in _section_items(section):
            item_id = _string_value(item.get("id"))
            if not item_id:
                continue
            identities = _item_identity_values(item, section_kind)
            if any(
                len(identity) >= 2 and _contains_term(prompt, identity)
                for identity in identities
                if identity
            ):
                item_fields[(section_id, item_id)] = requested_fields
                item_kinds.add(section_kind)

    # An explicitly named company/project is narrower than the generic section
    # word that naturally appears beside it (for example, "腾讯实习").
    mentioned_kinds.difference_update(item_kinds)

    if requested_fields and any(
        _contains_term(prompt, term) for term in _EXCLUSIVE_SCOPE_TERMS
    ):
        for kind in tuple(mentioned_kinds):
            items_in_kind = [
                (_string_value(section.get("id")), _string_value(item.get("id")))
                for section in sections
                if _string_value(section.get("kind")) == kind
                for item in _section_items(section)
                if _string_value(section.get("id")) and _string_value(item.get("id"))
            ]
            if len(items_in_kind) == 1:
                item_fields[items_in_kind[0]] = requested_fields
                mentioned_kinds.remove(kind)

    if "simple_list" in mentioned_kinds:
        matching_list_ids = {
            _string_value(section.get("id"))
            for section in sections
            if _string_value(section.get("kind")) == "simple_list"
            and _contains_term(prompt, _string_value(section.get("title")))
        }
        if matching_list_ids:
            mentioned_kinds.remove("simple_list")
            section_fields.update(
                (section_id, requested_fields)
                for section_id in matching_list_ids
                if section_id
            )

    if (
        requested_fields
        and has_resume_target
        and not (mentioned_kinds or section_fields or item_fields)
    ):
        mentioned_kinds.update(section["kind"] for section in SECTION_REGISTRY)

    if has_unresolved_scope:
        basic_fields.clear()
        mentioned_kinds.clear()
        section_fields.clear()
        item_fields.clear()

    revises_pending_relative_item = bool(
        request.draft_state
        and request.draft_state.status == "pending"
        and requested_fields
        and _PENDING_RELATIVE_ITEM_PATTERN.search(prompt)
    )

    if restores_pending_draft:
        basic_fields.clear()
        mentioned_kinds.clear()
        section_fields.clear()
        item_fields.clear()
        _add_pending_draft_scopes(
            request,
            basic_fields,
            section_fields,
            item_fields,
        )
    elif revises_pending_relative_item:
        basic_fields.clear()
        mentioned_kinds.clear()
        section_fields.clear()
        item_fields.clear()
        _add_pending_relative_item_scope(
            request,
            requested_fields,
            item_fields,
        )
    elif not (basic_fields or mentioned_kinds or section_fields or item_fields):
        _add_pending_draft_scopes(
            request,
            basic_fields,
            section_fields,
            item_fields,
        )

    has_scope = bool(basic_fields or mentioned_kinds or section_fields or item_fields)
    allow_all = not has_scope and not has_unresolved_scope and has_resume_target
    return EditAuthorization(
        allow_all=allow_all,
        allow_section_reorder=(
            has_explicit_reorder_intent(prompt)
            and not requested_fields
            and not item_fields
        ),
        basic_fields=frozenset(basic_fields),
        kind_fields=tuple(sorted((kind, requested_fields) for kind in mentioned_kinds)),
        section_fields=tuple(sorted(section_fields.items())),
        item_fields=tuple(
            sorted(
                (section_id, item_id, fields)
                for (section_id, item_id), fields in item_fields.items()
            ),
        ),
    )


def _add_pending_relative_item_scope(
    request: AgentChatRequest,
    requested_fields: frozenset[str],
    item_fields: dict[tuple[str, str], frozenset[str]],
) -> None:
    draft_state = request.draft_state
    if not draft_state or draft_state.status != "pending":
        return

    matching_targets: dict[tuple[str, str], set[str]] = {}
    for edit in draft_state.edits:
        operation = edit.get("operation") if isinstance(edit, dict) else None
        if not isinstance(operation, dict) or operation.get("type") != "update_item":
            continue
        fields = _item_fields(operation.get("patch")) & requested_fields
        section_id = _string_value(operation.get("sectionId"))
        item_id = _string_value(operation.get("itemId"))
        if fields and section_id and item_id:
            matching_targets.setdefault((section_id, item_id), set()).update(fields)

    if len(matching_targets) == 1:
        target, matched_fields = next(iter(matching_targets.items()))
        item_fields[target] = frozenset(matched_fields)


def unauthorized_edit_issues(
    authorization: EditAuthorization,
    resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Return operation-indexed scope failures without applying any edit."""

    issues: list[dict[str, Any]] = []
    section_kinds = {
        _string_value(section.get("id")): _string_value(section.get("kind"))
        for section in _resume_sections(resume)
    }
    for index, edit in enumerate(edits, start=1):
        operation = edit.operation
        if not isinstance(operation, dict):
            continue
        reason = authorization.rejection_reason(
            operation,
            _resume_with_section_kinds(resume, section_kinds),
        )
        if reason:
            issues.append({"index": index, "reason": reason})
            continue

        if operation.get("type") == "insert_section":
            section = operation.get("section")
            if isinstance(section, dict):
                section_id = _string_value(section.get("id"))
                section_kind = _string_value(section.get("kind"))
                if section_id:
                    section_kinds[section_id] = section_kind
    return issues


def unauthorized_plan_issues(
    authorization: EditAuthorization,
    resume: dict[str, Any],
    steps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return scope failures for plan steps that have no operation yet."""

    issues: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        reason = authorization.plan_target_rejection_reason(step, resume)
        if reason:
            issues.append({"index": index, "reason": reason})
    return issues


def _add_pending_draft_scopes(
    request: AgentChatRequest,
    basic_fields: set[str],
    section_fields: dict[str, frozenset[str]],
    item_fields: dict[tuple[str, str], frozenset[str]],
) -> None:
    draft_state = request.draft_state
    if not draft_state or draft_state.status != "pending":
        return

    for edit in draft_state.edits:
        if not isinstance(edit, dict):
            continue
        operation = edit.get("operation")
        if not isinstance(operation, dict):
            continue
        operation_type = _string_value(operation.get("type"))
        if operation_type == "replace_field":
            path = _string_value(operation.get("path"))
            if path.startswith("basic."):
                basic_fields.add(path.removeprefix("basic."))
        elif operation_type in {"update_item", "delete_item"}:
            section_id = _string_value(operation.get("sectionId"))
            item_id = _string_value(operation.get("itemId"))
            if section_id and item_id:
                item_fields[(section_id, item_id)] = _item_fields(
                    operation.get("patch"),
                )
        elif operation_type in {
            "insert_item",
            "update_section",
            "delete_section",
            "reorder_items",
        }:
            section_id = _string_value(operation.get("sectionId"))
            if section_id:
                section_fields[section_id] = frozenset()

    _add_pending_resume_diff_scopes(
        request,
        basic_fields,
        section_fields,
        item_fields,
    )


def _add_pending_resume_diff_scopes(
    request: AgentChatRequest,
    basic_fields: set[str],
    section_fields: dict[str, frozenset[str]],
    item_fields: dict[tuple[str, str], frozenset[str]],
) -> None:
    draft_state = request.draft_state
    if not draft_state:
        return
    base_resume = request.resume
    draft_resume = draft_state.resume

    base_basic = base_resume.get("basic")
    draft_basic = draft_resume.get("basic")
    if isinstance(base_basic, dict) and isinstance(draft_basic, dict):
        basic_fields.update(
            field
            for field in _BASIC_FIELD_TERMS
            if base_basic.get(field) != draft_basic.get(field)
        )

    base_sections = {
        _string_value(section.get("id")): section
        for section in _resume_sections(base_resume)
        if _string_value(section.get("id"))
    }
    draft_section_ids = {
        _string_value(section.get("id"))
        for section in _resume_sections(draft_resume)
        if _string_value(section.get("id"))
    }
    section_fields.update(
        (section_id, frozenset())
        for section_id in base_sections.keys() - draft_section_ids
    )
    for draft_section in _resume_sections(draft_resume):
        section_id = _string_value(draft_section.get("id"))
        base_section = base_sections.get(section_id)
        if base_section is None:
            section_fields[section_id] = frozenset()
            continue
        if base_section.get("title") != draft_section.get("title"):
            section_fields[section_id] = frozenset({"title"})

        base_items = {
            _string_value(item.get("id")): item
            for item in _section_items(base_section)
            if _string_value(item.get("id"))
        }
        draft_item_ids = {
            _string_value(item.get("id"))
            for item in _section_items(draft_section)
            if _string_value(item.get("id"))
        }
        item_fields.update(
            ((section_id, item_id), frozenset())
            for item_id in base_items.keys() - draft_item_ids
        )
        for draft_item in _section_items(draft_section):
            item_id = _string_value(draft_item.get("id"))
            base_item = base_items.get(item_id)
            if base_item is None:
                item_fields[(section_id, item_id)] = frozenset()
                continue
            changed_fields = frozenset(
                field
                for field in set(base_item) | set(draft_item)
                if field != "id" and base_item.get(field) != draft_item.get(field)
            )
            if changed_fields:
                item_fields[(section_id, item_id)] = changed_fields


def _requested_item_fields(prompt: str) -> frozenset[str]:
    if re.search(
        r"新增|添加|生成|新建|\b(?:create|add|insert)\b",
        prompt,
        flags=re.IGNORECASE,
    ):
        return frozenset()

    fields: set[str] = set()
    if any(_contains_term(prompt, term) for term in _BULLET_TERMS):
        fields.add("highlights")
    if any(_contains_term(prompt, term) for term in _TECH_STACK_TERMS):
        fields.add("techStack")
    if any(_contains_term(prompt, term) for term in _DESCRIPTION_TERMS):
        fields.add("description")
    fields.update(
        field
        for field, terms in _ITEM_FIELD_TERMS.items()
        if any(_contains_term(prompt, term) for term in terms)
    )
    return frozenset(fields)


def _fields_allow(
    allowed_fields: frozenset[str],
    requested_fields: frozenset[str],
) -> bool:
    return not allowed_fields or requested_fields.issubset(allowed_fields)


def _section_item_fields(value: object) -> frozenset[str]:
    if not isinstance(value, dict):
        return frozenset()
    items = value.get("items")
    if not isinstance(items, list):
        return frozenset()
    return frozenset(
        field
        for item in items
        if isinstance(item, dict)
        for field in item
        if field != "id"
    )


def _item_fields(value: object) -> frozenset[str]:
    if not isinstance(value, dict):
        return frozenset()
    return frozenset(field for field in value if field != "id")


def _resume_sections(resume: dict[str, Any]) -> list[dict[str, Any]]:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return []
    return [section for section in sections if isinstance(section, dict)]


def _section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    items = section.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _item_identity_values(item: dict[str, Any], kind: str) -> list[str]:
    values: list[str] = []
    for field in _ITEM_IDENTITY_FIELDS.get(kind, ()):
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            values.extend(_identity_candidates(value))
        elif isinstance(value, list):
            values.extend(
                candidate
                for entry in value
                if isinstance(entry, str) and entry.strip()
                for candidate in _identity_candidates(entry)
            )
    return list(dict.fromkeys(values))


def _identity_candidates(value: str) -> list[str]:
    text = value.strip()
    candidates = [text]
    for chunk in re.split(r"[|｜/、,，;；()（）\[\]【】]+", text):
        candidates.extend(_ROLE_MARKER_PATTERN.split(chunk))
    return [
        candidate.strip(" -—–·")
        for candidate in candidates
        if len(candidate.strip(" -—–·")) >= 2
    ]


def _section_kind(resume: dict[str, Any], section_id: str) -> str:
    for section in _resume_sections(resume):
        if _string_value(section.get("id")) == section_id:
            return _string_value(section.get("kind"))
    section_kinds = resume.get("_authorizationSectionKinds")
    if isinstance(section_kinds, dict):
        return _string_value(section_kinds.get(section_id))
    return ""


def _resume_with_section_kinds(
    resume: dict[str, Any],
    section_kinds: dict[str, str],
) -> dict[str, Any]:
    return {**resume, "_authorizationSectionKinds": section_kinds}


def _contains_term(text: str, term: str) -> bool:
    normalized_text = unicodedata.normalize("NFKC", text).casefold()
    normalized_term = unicodedata.normalize("NFKC", term).casefold().strip()
    if not normalized_term:
        return False
    if re.fullmatch(r"[a-z0-9_+#./-]+(?:\s+[a-z0-9_+#./-]+)*", normalized_term):
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                normalized_text,
            )
            is not None
        )
    return normalized_term in normalized_text


def _outside_scope(target: str) -> str:
    return (
        f"Edit target {target!r} is outside the scope authorized by the "
        "current user prompt."
    )


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
