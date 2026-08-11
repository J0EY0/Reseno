from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
)

from .attachments import AgentAttachmentError, attachment_text

_BASIC_FIELDS = frozenset(
    {
        "avatar",
        "email",
        "headline",
        "location",
        "name",
        "phone",
        "summary",
    },
)
_NUMERIC_CLAIM_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])\d+(?:[.,]\d+)?"
    r"(?:\s*(?:%|％|倍|x|ms|s|秒|分钟|小时|万|亿|k|m))?"
    r"(?![A-Za-z0-9_.])",
    flags=re.IGNORECASE,
)
_CHINESE_NUMERIC_CLAIM_PATTERN = re.compile(
    r"百分之[零〇一二三四五六七八九十百千万亿两]+|"
    r"[零〇一二三四五六七八九十百千万亿两]+"
    r"(?:倍|万|亿|毫秒|秒|分钟|小时|人|名|位)",
)
_TECH_TOKEN_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"[A-Za-z][A-Za-z0-9.+#-]*(?:/[A-Za-z0-9.+#-]+)*"
    r"(?![A-Za-z0-9])",
)
_KNOWN_TECHNOLOGY_TERMS = frozenset(
    {
        "angular",
        "ansible",
        "aws",
        "azure",
        "ci/cd",
        "cypress",
        "django",
        "docker",
        "elasticsearch",
        "fastapi",
        "firebase",
        "flask",
        "gcp",
        "git",
        "github",
        "gitlab",
        "graphql",
        "grpc",
        "hadoop",
        "java",
        "javascript",
        "jenkins",
        "jest",
        "kafka",
        "kubernetes",
        "mariadb",
        "mongodb",
        "mysql",
        "next.js",
        "nginx",
        "node.js",
        "numpy",
        "opensearch",
        "oracle",
        "pandas",
        "pinia",
        "playwright",
        "postgresql",
        "prisma",
        "prometheus",
        "pytorch",
        "python",
        "rabbitmq",
        "react",
        "redis",
        "redux",
        "rust",
        "selenium",
        "shadcn",
        "spark",
        "spring",
        "sql",
        "sqlite",
        "storybook",
        "supabase",
        "svelte",
        "tailwind",
        "tensorflow",
        "terraform",
        "typescript",
        "vercel",
        "vite",
        "vitest",
        "vue",
        "wcag",
        "webpack",
        "zustand",
    },
)
_TECHNOLOGY_TERM_ALIASES = {
    "tailwind css": "Tailwind",
}
_TECHNOLOGY_ALIAS_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])tailwind\s+css(?![A-Za-z0-9])",
    flags=re.IGNORECASE,
)
_MATERIAL_ASSERTION_TERMS = (
    "主导",
    "牵头",
    "带领",
    "跨部门",
    "独立负责",
    "独立完成",
    "管理团队",
    "领导团队",
    "晋升",
    "获奖",
)
_ENGLISH_MATERIAL_ASSERTION_PATTERN = re.compile(
    r"\b(?:led|owned|spearheaded|managed|cross-functional|awarded|promoted)\b",
    flags=re.IGNORECASE,
)
_CHINESE_MATERIAL_ASSERTION_PATTERN = re.compile(
    r"获得[^，。；;]{0,16}(?:奖|荣誉|最佳员工)|"
    r"管理[^，。；;]{0,8}团队|"
    r"推动[^，。；;]{0,12}(?:上市|增长|营收)",
)
_PROMPT_EVIDENCE_DENIAL_PATTERN = re.compile(
    r"没有证据|无证据|未做过|没做过|不存在|虚构|编造|假设|"
    r"即使没有|without\s+evidence|no\s+evidence|did\s+not|never\s+did|"
    r"invent|fabricat|pretend",
    flags=re.IGNORECASE,
)
_PROMPT_IMPERATIVE_PATTERN = re.compile(
    r"为了匹配|帮我|替我|"
    r"请(?:直接)?[^，。；;]{0,16}(?:写成|改成|包装成|补充|添加|加入|加上|写|改)|"
    r"直接(?:写成|改成|加上|加入|补充|添加)",
    flags=re.IGNORECASE,
)
_PROMPT_STRUCTURED_FACT_PATTERN = re.compile(
    r"候选人事实[:：]|项目事实[:：]|经历事实[:：]|简历事实[:：]|"
    r"项目名称[:：]|工作内容[:：]|技术栈[:：]|时间[:：]",
)
_PROMPT_FACT_PATTERN = re.compile(
    r"候选人事实[:：]|项目事实[:：]|经历事实[:：]|简历事实[:：]|事实是|"
    r"项目名称[:：]|工作内容[:：]|技术栈[:：]|时间[:：]|"
    r"我的技能[:：]|候选人技能[:：]|技能包括|"
    r"我(?:在|曾|已|负责|使用|采用|接入|实现|完成|主导|牵头|带领|管理)|"
    r"我们(?:在|曾|已|负责|使用|采用|接入|实现|完成|主导|牵头|带领|管理)|"
    r"本人(?:曾|已|负责|使用|采用|接入|实现|完成|主导|牵头|带领|管理)|"
    r"候选人(?:曾|已|负责|使用|采用|接入|实现|完成|主导|牵头|带领|管理)|"
    r"\b(?:i|we)\s+(?:built|used|implemented|integrated|achieved|reduced|"
    r"improved|delivered|maintained|owned|led)\b|"
    r"\bcandidate\s+(?:built|used|implemented|integrated|achieved|reduced|"
    r"improved|delivered|maintained|owned|led)\b",
    flags=re.IGNORECASE,
)
_NON_CLAIM_KEYS = frozenset(
    {
        "avatar",
        "email",
        "id",
        "itemId",
        "kind",
        "phone",
        "sectionId",
        "title",
        "url",
    },
)
_GROUNDING_STOP_UNITS = frozenset(
    {
        "与",
        "且",
        "以及",
        "使用",
        "依据",
        "和",
        "基于",
        "将",
        "并",
        "引入",
        "接入",
        "的",
    },
)
_GROUNDING_NON_CLAIM_PATTERN = re.compile(
    r"(?:技术栈|技能|更加?|精简|简洁|清晰|聚焦|突出|面向|内容|的)"
)


def ground_edit_evidence(
    before_resume: dict[str, Any],
    request: AgentChatRequest,
    edits: list[AgentResumeEditSuggestion],
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Attach candidate-owned evidence to every edit and reject foreign claims.

    Public target material can explain *why* an edit is relevant, but it cannot
    prove that the candidate has an experience or result. The allowlist below
    therefore contains only the current resume, current user turn, and current
    attachments. Missing model references are inferred from the operation so
    Response edits remain traceable to the supporting source identifiers.
    """

    allowed_refs = _allowed_evidence_refs(before_resume, request)
    grounded_edits: list[AgentResumeEditSuggestion] = []
    issues: list[dict[str, Any]] = []

    for operation_index, edit in enumerate(edits, start=1):
        provided_refs = _unique_strings(edit.evidence_refs)
        invalid_refs = [
            reference for reference in provided_refs if reference not in allowed_refs
        ]
        if invalid_refs:
            issues.append(
                {
                    "code": "invalid_edit_evidence",
                    "severity": "error",
                    "target": edit.target,
                    "scope": "evidence",
                    "operationIndex": operation_index,
                    "invalidEvidenceRefs": invalid_refs,
                },
            )

        evidence_refs = provided_refs or _inferred_evidence_refs(
            edit.operation,
            allowed_refs,
        )
        if not evidence_refs:
            issues.append(
                {
                    "code": "missing_edit_evidence",
                    "severity": "error",
                    "target": edit.target,
                    "scope": "evidence",
                    "operationIndex": operation_index,
                },
            )

        unsupported_claims = _unsupported_new_claims(
            before_resume,
            request,
            edit.operation,
            evidence_refs,
        )
        if unsupported_claims:
            issues.append(
                {
                    "code": "unsupported_edit_claim",
                    "severity": "error",
                    "target": edit.target,
                    "scope": "evidence",
                    "operationIndex": operation_index,
                    "claims": unsupported_claims,
                },
            )

        grounded_edits.append(
            edit.model_copy(update={"evidence_refs": evidence_refs}),
        )

    return grounded_edits, issues


def _unsupported_new_claims(
    resume: dict[str, Any],
    request: AgentChatRequest,
    operation: dict[str, Any] | None,
    evidence_refs: list[str],
) -> list[str]:
    if _restoration_content_mismatch(resume, request.resume, operation):
        return ["restoration_content_mismatch"]

    before_text, candidate_text = _operation_claim_text(resume, operation)
    before_claims = _claims_in_text(before_text) | _operation_tech_stack_claims(
        resume,
        operation,
        before=True,
    )
    candidate_claims = _claims_in_text(
        candidate_text,
    ) | _operation_tech_stack_claims(resume, operation, before=False)
    before_keys = {claim.casefold() for claim in before_claims}
    new_claims = {
        claim for claim in candidate_claims if claim.casefold() not in before_keys
    }
    evidence_by_ref = {
        reference: _evidence_text(resume, request, reference)
        for reference in evidence_refs
    }
    unsupported_claims = sorted(
        claim
        for claim in new_claims
        if not any(
            _reference_supports_claim(
                reference,
                evidence_text,
                request.message.text,
                claim,
            )
            for reference, evidence_text in evidence_by_ref.items()
        )
    )
    grounding_texts = [before_text]
    for reference, evidence_text in evidence_by_ref.items():
        if reference == "prompt:current":
            grounding_texts.extend(_factual_prompt_sentences(request.message.text))
        else:
            grounding_texts.append(evidence_text)
    unsupported_content = [
        f"text:{clause[:80]}"
        for clause in _substantive_clauses(candidate_text)
        if not any(_text_contains_claim(clause, claim) for claim in unsupported_claims)
        and not _clause_is_grounded(clause, grounding_texts)
    ]
    return sorted({*unsupported_claims, *unsupported_content})


def _restoration_content_mismatch(
    active_resume: dict[str, Any],
    formal_resume: dict[str, Any],
    operation: dict[str, Any] | None,
) -> bool:
    if not isinstance(operation, dict):
        return False

    operation_type = _string_value(operation.get("type"))
    if operation_type == "insert_item":
        section_id = _string_value(operation.get("sectionId"))
        item = operation.get("item")
        item_id = _string_value(item.get("id")) if isinstance(item, dict) else ""
        formal_item = _find_item(_find_section(formal_resume, section_id), item_id)
        if formal_item is None or _resume_has_item(active_resume, item_id):
            return False
        return item != formal_item

    if operation_type == "insert_section":
        section = operation.get("section")
        section_id = (
            _string_value(section.get("id")) if isinstance(section, dict) else ""
        )
        formal_section = _find_section(formal_resume, section_id)
        if (
            formal_section is None
            or _find_section(active_resume, section_id) is not None
        ):
            return False
        return section != formal_section

    return False


def _resume_has_item(resume: dict[str, Any], item_id: str) -> bool:
    sections = resume.get("sections")
    return isinstance(sections, list) and any(
        _find_item(section, item_id) is not None
        for section in sections
        if isinstance(section, dict)
    )


def _operation_claim_text(
    resume: dict[str, Any],
    operation: dict[str, Any] | None,
) -> tuple[str, str]:
    if not isinstance(operation, dict):
        return "", ""

    operation_type = _string_value(operation.get("type"))
    if operation_type == "replace_field":
        path = _string_value(operation.get("path"))
        field = path.removeprefix("basic.") if path.startswith("basic.") else ""
        basic = resume.get("basic")
        before = basic.get(field) if isinstance(basic, dict) else ""
        return _flatten_text(before), _flatten_text(operation.get("value"))

    section_id = _string_value(operation.get("sectionId"))
    section = _find_section(resume, section_id)
    if operation_type == "update_section":
        patch = operation.get("patch")
        return _matching_before_text(section, patch), _flatten_text(patch)

    if operation_type == "insert_section":
        return "", _flatten_text(operation.get("section"))

    if operation_type == "insert_item":
        return "", _flatten_text(operation.get("item"))

    if operation_type == "update_item":
        item = _find_item(section, _string_value(operation.get("itemId")))
        patch = operation.get("patch")
        return _matching_before_text(item, patch), _flatten_text(patch)

    return "", ""


def _matching_before_text(value: object, patch: object) -> str:
    if not isinstance(value, dict) or not isinstance(patch, dict):
        return ""
    return _flatten_text(
        {key: value.get(key) for key in patch if key not in _NON_CLAIM_KEYS},
    )


def _claims_in_text(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _TECHNOLOGY_ALIAS_PATTERN.sub("Tailwind", normalized)
    claims = {
        re.sub(r"\s+", "", match.group(0))
        for match in _NUMERIC_CLAIM_PATTERN.finditer(normalized)
    }
    claims.update(
        match.group(0) for match in _CHINESE_NUMERIC_CLAIM_PATTERN.finditer(normalized)
    )
    claims.update(term for term in _MATERIAL_ASSERTION_TERMS if term in normalized)
    claims.update(
        match.group(0)
        for match in _CHINESE_MATERIAL_ASSERTION_PATTERN.finditer(normalized)
    )
    claims.update(
        match.group(0)
        for match in _ENGLISH_MATERIAL_ASSERTION_PATTERN.finditer(normalized)
    )
    for match in _TECH_TOKEN_PATTERN.finditer(normalized):
        token = match.group(0)
        token_key = token.casefold()
        if token_key in _KNOWN_TECHNOLOGY_TERMS or (
            len(token) >= 2 and token.isupper()
        ):
            claims.add(token)
    return claims


def _reference_supports_claim(
    reference: str,
    evidence_text: str,
    prompt: str,
    claim: str,
) -> bool:
    if reference == "prompt:current":
        return _prompt_supports_claim(prompt, claim)
    return _text_contains_claim(evidence_text, claim)


def _prompt_supports_claim(prompt: str, claim: str) -> bool:
    return any(
        _text_contains_claim(sentence, claim)
        for sentence in _factual_prompt_sentences(prompt)
    )


def _factual_prompt_sentences(prompt: str) -> list[str]:
    has_structured_candidate_context = bool(
        _PROMPT_STRUCTURED_FACT_PATTERN.search(prompt),
    )
    factual_segments: list[str] = []
    for sentence in re.split(r"[。!?！？;；\n]+|(?<!\d)\.(?!\d)", prompt):
        sentence = sentence.strip()
        if not sentence:
            continue
        has_fact_context = bool(
            _PROMPT_FACT_PATTERN.search(sentence)
            or (has_structured_candidate_context and re.match(r"^\s*负责", sentence)),
        )
        if not has_fact_context:
            continue
        factual_segments.extend(
            segment
            for segment in _split_inner_clauses(sentence)
            if not _PROMPT_EVIDENCE_DENIAL_PATTERN.search(segment)
            and (
                not _PROMPT_IMPERATIVE_PATTERN.search(segment)
                or _PROMPT_STRUCTURED_FACT_PATTERN.search(segment)
            )
        )
    return factual_segments


def _substantive_clauses(text: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(
            r"[。!?！？;；，,、\n]+|(?:并且|同时|以及|但是|但)|"
            r"(?<!合)并(?!发|行|购)|且|与|\b(?:and|but)\b",
            text,
            flags=re.IGNORECASE,
        )
        if len(_normalize_grounding_text(clause)) >= 3
    ]


def _split_inner_clauses(text: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(
            r"[，,、]+|(?:并且|同时|以及|但是|但)|"
            r"(?<!合)并(?!发|行|购)|且|与|\b(?:and|but)\b",
            text,
            flags=re.IGNORECASE,
        )
        if segment.strip()
    ]


def _clause_is_grounded(clause: str, evidence_texts: list[str]) -> bool:
    candidate = _normalize_grounding_text(clause)
    if not candidate:
        return True

    evidence_values = [
        evidence
        for text in evidence_texts
        if (evidence := _normalize_grounding_text(text))
    ]
    if any(candidate in evidence for evidence in evidence_values):
        return True

    contained_evidence = [
        evidence
        for evidence in evidence_values
        if len(evidence) >= 4 and evidence in candidate
    ]
    if contained_evidence:
        return any(
            _clause_is_grounded(
                _GROUNDING_NON_CLAIM_PATTERN.sub(
                    "",
                    candidate.replace(evidence, " ", 1),
                ),
                [other for other in evidence_values if other != evidence],
            )
            for evidence in contained_evidence
        )

    candidate_units = _grounding_units(candidate)
    all_evidence_units: set[str] = set()
    blocked_insertion = False
    for evidence in evidence_values:
        if not candidate_units:
            continue
        evidence_units = _grounding_units(evidence)
        all_evidence_units.update(evidence_units)
        overlap = len(candidate_units & evidence_units)
        required_overlap = 1 if len(candidate_units) < 3 else 2
        if overlap >= required_overlap and overlap / len(candidate_units) >= 0.5:
            if _has_unsupported_insertion(candidate, evidence):
                blocked_insertion = True
            else:
                return True
    overlap = len(candidate_units & all_evidence_units)
    required_overlap = 1 if len(candidate_units) < 3 else 2
    return (
        not blocked_insertion
        and overlap >= required_overlap
        and overlap / len(candidate_units) >= 0.5
    )


def _has_unsupported_insertion(candidate: str, evidence: str) -> bool:
    for tag, _start, _end, candidate_start, candidate_end in SequenceMatcher(
        None,
        evidence,
        candidate,
    ).get_opcodes():
        if tag != "insert":
            continue
        inserted = _GROUNDING_NON_CLAIM_PATTERN.sub(
            "",
            candidate[candidate_start:candidate_end],
        )
        if len(re.sub(r"[^\u3400-\u9fff]", "", inserted)) >= 3:
            return True
    return False


def _normalize_grounding_text(value: str) -> str:
    normalized = re.sub(
        r"[^a-z0-9.+#/\-\u3400-\u9fff]+",
        " ",
        unicodedata.normalize("NFKC", value).casefold(),
    )
    return " ".join(normalized.split())


def _grounding_units(value: str) -> set[str]:
    value = _GROUNDING_NON_CLAIM_PATTERN.sub("", value)
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", value)
    cjk_units = {
        run[index : index + 2]
        for run in cjk_runs
        for index in range(max(1, len(run) - 1))
        if run[index : index + 2] not in _GROUNDING_STOP_UNITS
    }
    latin_units = {
        token
        for token in re.findall(r"[a-z][a-z0-9.+#/-]+", value)
        if token not in {"and", "for", "the", "with", "from", "into"}
    }
    return cjk_units | latin_units


def _operation_tech_stack_claims(
    resume: dict[str, Any],
    operation: dict[str, Any] | None,
    *,
    before: bool,
) -> set[str]:
    if not isinstance(operation, dict):
        return set()

    operation_type = _string_value(operation.get("type"))
    if operation_type == "insert_section":
        value = None if before else operation.get("section")
    elif operation_type == "insert_item":
        value = None if before else operation.get("item")
    elif operation_type == "update_item":
        section = _find_section(resume, _string_value(operation.get("sectionId")))
        item = _find_item(section, _string_value(operation.get("itemId")))
        value = item if before else operation.get("patch")
    else:
        return set()
    return _tech_stack_values(value)


def _tech_stack_values(value: object) -> set[str]:
    if not isinstance(value, dict):
        return set()
    claims = {
        _canonical_technology_term(claim)
        for claim in _string_list(value.get("techStack"))
    }
    items = value.get("items")
    if isinstance(items, list):
        claims.update(
            _canonical_technology_term(claim)
            for item in items
            if isinstance(item, dict)
            for claim in _string_list(item.get("techStack"))
        )
    return claims


def _canonical_technology_term(value: str) -> str:
    key = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return _TECHNOLOGY_TERM_ALIASES.get(key, value)


def _text_contains_claim(text: str, claim: str) -> bool:
    normalized_text = unicodedata.normalize("NFKC", text).casefold()
    normalized_claim = unicodedata.normalize("NFKC", claim).casefold().strip()
    if not normalized_claim:
        return False
    if re.fullmatch(r"[a-z0-9.+#/-]+", normalized_claim):
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_claim)}(?![a-z0-9])",
                normalized_text,
            )
            is not None
        )
    return normalized_claim in normalized_text


def _evidence_text(
    resume: dict[str, Any],
    request: AgentChatRequest,
    reference: str,
) -> str:
    if reference == "prompt:current":
        return str(request.message.text)

    if reference.startswith("resume:basic:"):
        field = reference.removeprefix("resume:basic:")
        basic = resume.get("basic")
        return _flatten_text(basic.get(field) if isinstance(basic, dict) else "")

    if reference.startswith("resume:section:"):
        section_id = reference.removeprefix("resume:section:")
        section = _find_section(resume, section_id)
        if section is None:
            section = _find_section(request.resume, section_id)
        return _flatten_text(section)

    if reference.startswith("resume:item:"):
        parts = reference.split(":", maxsplit=3)
        if len(parts) != 4:
            return ""
        section = _find_section(resume, parts[2])
        item = _find_item(section, parts[3])
        if item is None:
            section = _find_section(request.resume, parts[2])
            item = _find_item(section, parts[3])
        return _flatten_text(item)

    if reference.startswith("attachment:"):
        attachment_id = reference.removeprefix("attachment:")
        file = next(
            (
                candidate
                for candidate in _request_files(request)
                if _string_value(candidate.get("id")) == attachment_id
            ),
            None,
        )
        session_id = (request.resume_id or "").strip()
        if file is None or not session_id:
            return ""
        try:
            return str(attachment_text(session_id, file))
        except AgentAttachmentError:
            return ""
    return ""


def _find_section(resume: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return None
    return next(
        (
            section
            for section in sections
            if isinstance(section, dict)
            and _string_value(section.get("id")) == section_id
        ),
        None,
    )


def _find_item(
    section: dict[str, Any] | None,
    item_id: str,
) -> dict[str, Any] | None:
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and _string_value(item.get("id")) == item_id
        ),
        None,
    )


def _flatten_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            _flatten_text(item)
            for key, item in value.items()
            if key not in _NON_CLAIM_KEYS
        )
    return ""


def _allowed_evidence_refs(
    resume: dict[str, Any],
    request: AgentChatRequest,
) -> set[str]:
    refs = {f"resume:basic:{field}" for field in _BASIC_FIELDS}
    refs.add("prompt:current")

    for evidence_resume in (resume, request.resume):
        sections = evidence_resume.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_id = _string_value(section.get("id"))
            if not section_id:
                continue
            refs.add(f"resume:section:{section_id}")
            items = section.get("items")
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_id = _string_value(item.get("id"))
                if item_id:
                    refs.add(f"resume:item:{section_id}:{item_id}")

    for attachment in _request_files(request):
        attachment_id = _string_value(attachment.get("id"))
        if attachment_id:
            refs.add(f"attachment:{attachment_id}")
    return refs


def _inferred_evidence_refs(
    operation: dict[str, Any] | None,
    allowed_refs: set[str],
) -> list[str]:
    if not isinstance(operation, dict):
        return []

    operation_type = _string_value(operation.get("type"))
    refs: list[str] = []
    section_id = _string_value(operation.get("sectionId"))
    item_id = _string_value(operation.get("itemId"))
    inserted_item = operation.get("item")
    inserted_section = operation.get("section")
    if operation_type == "insert_item" and isinstance(inserted_item, dict):
        item_id = _string_value(inserted_item.get("id"))
    if operation_type == "insert_section" and isinstance(inserted_section, dict):
        section_id = _string_value(inserted_section.get("id"))

    if operation_type == "replace_field":
        path = _string_value(operation.get("path"))
        if path.startswith("basic."):
            refs.append(f"resume:basic:{path.removeprefix('basic.')}")
    elif operation_type in {"update_item", "delete_item"}:
        refs.append(f"resume:item:{section_id}:{item_id}")
    elif operation_type == "insert_item":
        item_ref = f"resume:item:{section_id}:{item_id}"
        refs.append(
            item_ref if item_ref in allowed_refs else f"resume:section:{section_id}"
        )
    elif operation_type in {"update_section", "delete_section", "reorder_items"}:
        refs.append(f"resume:section:{section_id}")
    elif operation_type == "insert_section":
        refs.append(f"resume:section:{section_id}")
    elif operation_type == "reorder_sections":
        refs.extend(
            f"resume:section:{section_id}"
            for section_id in _string_list(operation.get("sectionIds"))
        )

    # The current turn records the user's intent and any pasted source text.
    # Attachments are allowed only when the model references one explicitly;
    # inferring every uploaded file here would claim evidence the edit may not
    # have used.
    if operation_type in {
        "insert_item",
        "insert_section",
        "replace_field",
        "update_item",
        "update_section",
    }:
        refs.append("prompt:current")

    return [
        reference for reference in _unique_strings(refs) if reference in allowed_refs
    ]


def _request_files(request: AgentChatRequest) -> list[dict[str, Any]]:
    return [file for file in request.message.files if isinstance(file, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if isinstance(item, str) and (text := item.strip())]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
