import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentTargetContext,
)

TargetContextUpdateMode = Literal["merge", "replace", "clear"]

_MODEL_FIELDS = {
    "kind",
    "target",
    "locations",
    "seniority",
    "responsibilities",
    "mustHaveSkills",
    "niceToHaveSkills",
    "requirements",
    "description",
    "exactJobDescription",
}
_NEGATED_TARGET_RESEARCH = re.compile(
    r"(?:不要|无需|不需要|别|请勿|do not|don't|dont|no need to)"
    r".{0,16}(?:检索|搜索|查找|查询|search|research|find)"
    r".{0,16}(?:岗位|职位|工作|jd|role|job)",
    flags=re.IGNORECASE,
)
_NEGATED_TARGET_CLEAR = re.compile(
    r"(?:不要|别|请勿).{0,8}(?:清除|清空|忘掉|取消|移除).{0,12}(?:目标|岗位|职位|jd)",
    flags=re.IGNORECASE,
)
_AFFIRMATIVE_TARGET_CLEAR = re.compile(
    r"(?:(?:清除|清空|忘掉|取消|移除).{0,12}(?:目标|岗位|职位|jd)|"
    r"(?:目标|岗位|职位|jd).{0,12}(?:清除|清空|忘掉|取消|移除)|"
    r"(?:不再|不要再).{0,8}(?:针对|使用|沿用).{0,12}(?:目标|岗位|职位|jd)|"
    r"(?:clear|forget|remove).{0,12}(?:target|role|job description|jd)|"
    r"stop using.{0,12}(?:target|role|job description|jd))",
    flags=re.IGNORECASE,
)
_EXPLICIT_TARGET_CHANGE = re.compile(
    r"(?:换成|改成|改为|目标(?:是|为)|我要投|想投|申请|地点(?:改|换)|"
    r"switch to|change to|target is|apply(?:ing)? (?:to|for))",
    flags=re.IGNORECASE,
)
_EXPLICIT_TARGET_REPLACEMENT = re.compile(
    r"(?:换成|改为|目标(?:是|为)|我要投|想投|申请|"
    r"switch to|change to|target is|apply(?:ing)? (?:to|for))",
    flags=re.IGNORECASE,
)
_EXACT_JD_MARKER = re.compile(
    r"(?:(?:岗位职责|工作职责|职位职责|工作内容|岗位描述|职位描述|职责|"
    r"任职要求|岗位要求|职位要求|资格要求|任职资格)"
    r"[ \t]*(?:[:：]|(?=\r?$))|"
    r"^(?:岗位职责|工作职责|职位职责|工作内容|岗位描述|职位描述|职责|"
    r"任职要求|岗位要求|职位要求|资格要求|任职资格)[ \t]+(?=\S)|"
    r"(?:responsibilities?|requirements?|qualifications?)"
    r"[ \t]*(?::|(?=\r?$))|"
    r"^(?:responsibilities?|requirements?|qualifications?)[ \t]+(?=\S))",
    flags=re.IGNORECASE | re.MULTILINE,
)
_TARGET_CONTROL_SENTENCE = re.compile(
    r"^(?:请|只|仅|不要|无需|别|please|only|do not|don't).{0,40}"
    r"(?:修改|优化|分析|检索|搜索|写入|edit|rewrite|analy[sz]e|search)",
    flags=re.IGNORECASE,
)
_EXACT_JD_DOWNGRADE = re.compile(
    r"(?:不是|并非|不再|忽略|清除).{0,16}(?:完整|精确|jd|职位描述|job description)",
    flags=re.IGNORECASE,
)
_PARTIAL_JD_DECLARATION = re.compile(
    r"(?:(?:不是|并非|不属于).{0,8}(?:完整|精确).{0,4}(?:jd|职位描述)|"
    r"(?:not|isn't|is not).{0,8}(?:complete|exact).{0,8}"
    r"(?:jd|job description))",
    flags=re.IGNORECASE,
)
_CJK_ROLE_SUFFIX = re.compile(
    r"(?:工程师|开发者?|负责人|经理|专家|岗位|职位)$",
)
_LATIN_TERM = re.compile(r"[a-z0-9]+(?:[+#]{1,2})?", flags=re.IGNORECASE)
_CJK_SEQUENCE = re.compile(r"[\u3400-\u9fff]+")
_SHORT_TECH_TERMS = {"ai", "ml", "ui", "ux", "qa", "go", "c#", "c++", "ci", "cd"}
_GENERIC_ROLE_TERMS = {
    "developer",
    "engineer",
    "manager",
    "role",
    "specialist",
}
_GENERIC_ROLE_BIGRAMS = {"岗位", "职位", "工程", "程师"}


def target_context_from_request(request: AgentChatRequest) -> AgentTargetContext | None:
    """Return the latest structured target from authoritative conversation history."""

    return target_context_from_history(request.messages)


def target_context_from_history(
    messages: list[AgentConversationItem],
) -> AgentTargetContext | None:
    """Read the last assistant-owned target context from stored response JSON."""

    for message in reversed(messages):
        response = message.response
        if message.role != "assistant" or not isinstance(response, dict):
            continue
        value = response.get("targetContext")
        if value is None:
            continue
        context = AgentTargetContext.model_validate(value)
        return None if context.cleared else context
    return None


def rejects_target_context_update(prompt: str) -> bool:
    """Reject an obvious negated research command as target-memory input."""

    return bool(
        _NEGATED_TARGET_RESEARCH.search(prompt)
        and not _EXPLICIT_TARGET_CHANGE.search(prompt)
    )


def clears_target_context(prompt: str) -> bool:
    """Return whether the user explicitly asked to forget the remembered target."""

    return bool(
        _AFFIRMATIVE_TARGET_CLEAR.search(prompt)
        and not _NEGATED_TARGET_CLEAR.search(prompt)
    )


def exact_job_description_from_prompt(prompt: str) -> str:
    """Extract only the responsibility/qualification block from a pasted prompt."""

    marker = _EXACT_JD_MARKER.search(prompt)
    if marker is None:
        return ""
    excerpt = prompt[marker.start() :].strip()
    for boundary in re.finditer(r"(?<=[。！？；;])|(?<=[.!?])\s+|\n+", excerpt):
        following = excerpt[boundary.end() :].lstrip()
        if _TARGET_CONTROL_SENTENCE.search(following):
            return excerpt[: boundary.start()].rstrip("；;").strip()
    return excerpt


def prompt_declares_partial_job_description(prompt: str) -> bool:
    """Return whether the user explicitly says the supplied target is not a full JD."""

    return bool(_PARTIAL_JD_DECLARATION.search(prompt))


def target_context_update_is_grounded(
    current: AgentTargetContext | None,
    patch: Mapping[str, Any],
    *,
    mode: TargetContextUpdateMode,
    prompt: str,
) -> bool:
    """Return whether a semantic context change is supported by this prompt."""

    proposed = update_target_context(
        current,
        patch,
        mode=mode,
        source_message_id="",
    )
    before = _semantic_values(current)
    after = _semantic_values(proposed)
    if before == after:
        return False

    target_changed = bool(
        current
        and proposed.target
        and proposed.target.casefold() != current.target.casefold()
    )
    if target_changed and mode != "replace":
        return False

    if current is not None and mode == "replace":
        complete_description = _is_exact_description_from_prompt(
            proposed.description,
            prompt,
        )
        if not complete_description and (
            not target_changed or not _EXPLICIT_TARGET_REPLACEMENT.search(prompt)
        ):
            return False

    current_kind = current.kind if current is not None else "general"
    if proposed.kind != current_kind and not _kind_is_grounded(
        proposed.kind,
        prompt,
    ):
        return False

    exact_became_true = proposed.exact_job_description and not (
        current and current.exact_job_description
    )
    if exact_became_true and not _is_exact_description_from_prompt(
        proposed.description,
        prompt,
    ):
        return False
    if (
        current
        and current.exact_job_description
        and not proposed.exact_job_description
        and not target_changed
        and not _EXACT_JD_DOWNGRADE.search(prompt)
    ):
        return False

    changed_text: list[str] = []
    for field in _MODEL_FIELDS - {"kind", "exactJobDescription"}:
        previous = before.get(field)
        candidate = after.get(field)
        if previous == candidate:
            continue
        if isinstance(candidate, list):
            previous_values = previous if isinstance(previous, list) else []
            additions = [
                value
                for value in candidate
                if isinstance(value, str) and value not in previous_values
            ]
            changed_text.extend(additions)
            if mode == "merge" and not _list_replacement_is_explicit(
                field,
                prompt,
            ):
                changed_text.extend(
                    value
                    for value in previous_values
                    if isinstance(value, str) and value not in candidate
                )
        elif isinstance(candidate, str) and candidate:
            changed_text.append(candidate)
        elif isinstance(previous, str) and previous and mode == "merge":
            changed_text.append(previous)

    grounded_changes = [value for value in changed_text if value.strip()]
    if not grounded_changes:
        return bool(_EXPLICIT_TARGET_CHANGE.search(prompt))
    return all(_text_is_grounded_in_prompt(value, prompt) for value in grounded_changes)


def update_target_context(
    current: AgentTargetContext | None,
    patch: Mapping[str, Any],
    *,
    mode: TargetContextUpdateMode,
    source_message_id: str,
) -> AgentTargetContext:
    """Apply one model-selected replacement or incremental context update."""

    unknown_fields = set(patch) - _MODEL_FIELDS
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"Unknown target context fields: {names}")

    if mode == "clear":
        if patch:
            raise ValueError("Clear target context does not accept context fields.")
        return AgentTargetContext(
            cleared=True,
            sourceMessageIds=[source_message_id] if source_message_id else [],
        )

    values = (
        current.model_dump(mode="python", by_alias=True)
        if mode == "merge" and current is not None
        else {}
    )
    values.update(patch)
    source_ids = (
        list(current.source_message_ids)
        if mode == "merge" and current is not None
        else []
    )
    if source_message_id and source_message_id not in source_ids:
        source_ids.append(source_message_id)
    values["sourceMessageIds"] = source_ids[-40:]
    return AgentTargetContext.model_validate(values)


def _semantic_values(context: AgentTargetContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    values = context.model_dump(mode="python", by_alias=True)
    values.pop("sourceMessageIds", None)
    return values


def _text_is_grounded_in_prompt(value: str, prompt: str) -> bool:
    candidate = _compact_text(value)
    source = _compact_text(prompt)
    if not candidate:
        return False
    normalized_candidate = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized_source = unicodedata.normalize("NFKC", prompt).casefold()
    if re.search(
        rf"(?<![\w+#]){re.escape(normalized_candidate)}(?![\w+#])",
        normalized_source,
    ):
        return True

    candidate_latin = {
        term
        for term in _LATIN_TERM.findall(unicodedata.normalize("NFKC", value).casefold())
        if (len(term) > 2 or term in _SHORT_TECH_TERMS)
        and term not in _GENERIC_ROLE_TERMS
    }
    source_latin = set(
        _LATIN_TERM.findall(unicodedata.normalize("NFKC", prompt).casefold()),
    )
    if candidate_latin and not candidate_latin.issubset(source_latin):
        return False

    candidate_cjk = [
        _CJK_ROLE_SUFFIX.sub("", sequence) for sequence in _CJK_SEQUENCE.findall(value)
    ]
    if candidate_cjk:
        if any(
            len(sequence) == 1 and sequence not in source for sequence in candidate_cjk
        ):
            return False
        bigrams = {
            sequence[index : index + 2]
            for sequence in candidate_cjk
            for index in range(len(sequence) - 1)
        } - _GENERIC_ROLE_BIGRAMS
        if bigrams:
            matched = sum(bigram in source for bigram in bigrams)
            if matched / len(bigrams) < 0.8:
                return False

    return bool(candidate_latin or any(candidate_cjk))


def _compact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _kind_is_grounded(kind: str, prompt: str) -> bool:
    patterns = {
        "employment": (
            r"(?:岗位|职位|工作|工程师|开发|我要投|想投|"
            r"job|role|engineer|developer)"
        ),
        "graduate_study": r"(?:硕士|博士|研究生|招生|graduate|master|phd|program)",
        "research": r"(?:科研|研究|实验室|research|laboratory|\blab\b)",
        "scholarship": r"(?:奖学金|scholarship|fellowship)",
        "general": r"(?:目标|机会|target|opportunity)",
    }
    return bool(re.search(patterns[kind], prompt, flags=re.IGNORECASE))


def _is_exact_description_from_prompt(description: str, prompt: str) -> bool:
    compact_description = _compact_text(description)
    extracted = exact_job_description_from_prompt(prompt)
    return bool(
        len(compact_description) >= 24
        and _EXACT_JD_MARKER.search(description)
        and description.strip() == extracted
    )


def _list_replacement_is_explicit(field: str, prompt: str) -> bool:
    patterns = {
        "locations": r"(?:地点|地区|城市).{0,8}(?:改成|改为|换成|换到)",
        "mustHaveSkills": r"(?:必备|硬性|技能|要求).{0,8}(?:改成|替换|仅保留|只需要)",
        "niceToHaveSkills": r"(?:加分|可选|技能|要求).{0,8}(?:改成|替换|仅保留|只需要)",
        "responsibilities": r"(?:职责|工作内容).{0,8}(?:改成|替换|仅保留)",
        "requirements": r"(?:要求|资格).{0,8}(?:改成|替换|仅保留)",
    }
    pattern = patterns.get(field)
    return bool(pattern and re.search(pattern, prompt, flags=re.IGNORECASE))


def target_context_text(context: AgentTargetContext | None) -> str:
    """Render structured target facts into compact model/reference context."""

    if context is None or context.cleared:
        return ""

    lines: list[str] = []
    if context.target:
        lines.append(f"Target: {context.target}")
    if context.locations:
        lines.append(f"Locations: {', '.join(context.locations)}")
    if context.seniority:
        lines.append(f"Seniority: {context.seniority}")
    _append_values(lines, "Responsibilities", context.responsibilities)
    _append_values(lines, "Must-have skills", context.must_have_skills)
    _append_values(lines, "Nice-to-have skills", context.nice_to_have_skills)
    _append_values(lines, "Requirements", context.requirements)
    if context.description:
        lines.append(f"Description: {context.description}")
    return "\n".join(lines)


def target_context_requirements(context: AgentTargetContext | None) -> list[str]:
    """Return stable, explicit matching inputs without conversation instructions."""

    if context is None or context.cleared:
        return []
    return _deduplicate(
        [
            *context.must_have_skills,
            *context.nice_to_have_skills,
            *context.requirements,
            *context.responsibilities,
        ],
    )


def _append_values(lines: list[str], label: str, values: list[str]) -> None:
    if values:
        lines.append(f"{label}: {'; '.join(values)}")


def _deduplicate(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split()).strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result
