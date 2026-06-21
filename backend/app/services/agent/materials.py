import re
from typing import Any

from .parsing_patterns import compiled_agent_pattern, matches_agent_pattern
from .privacy import sanitize_agent_text

MAX_MATERIAL_CANDIDATES = 8
DEFAULT_MATERIAL_CANDIDATES = 6
MAX_MATERIAL_EXCERPT_CHARS = 240
MATERIAL_FOCI = {
    "all",
    "resume_facts",
    "experience",
    "project",
    "work",
    "internship",
    "skills",
    "education",
    "jd",
}
SECTION_PATTERNS = (
    ("project", "material.project"),
    ("work", "material.work"),
    ("internship", "material.internship"),
    ("skills", "material.skills"),
    ("education", "material.education"),
    ("awards", "material.awards"),
    ("certificates", "material.certificates"),
)
FOCUS_SECTIONS = {
    "experience": {"project", "work", "internship"},
    "project": {"project"},
    "work": {"work"},
    "internship": {"internship"},
    "skills": {"skills"},
    "education": {"education"},
}


def extract_resume_materials(
    *,
    prompt: str,
    job_brief: str,
    files: list[dict[str, Any]],
    focus: str = "all",
    max_items: int = DEFAULT_MATERIAL_CANDIDATES,
    hidden_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Extract bounded resume-useful snippets from user-provided materials."""

    resolved_focus = focus if focus in MATERIAL_FOCI else "all"
    limit = _bounded_max_items(max_items)
    sources = _material_sources(
        prompt=prompt,
        job_brief=job_brief,
        files=files,
        hidden_terms=hidden_terms,
    )
    candidates = _material_candidates(sources, focus=resolved_focus, limit=limit)
    fallback_used = False

    if not candidates and resolved_focus in {"all", "resume_facts"}:
        candidates = _fallback_candidates(sources, focus=resolved_focus, limit=limit)
        fallback_used = bool(candidates)

    return {
        "sourceCount": len(sources),
        "candidateCount": len(candidates),
        "focus": resolved_focus,
        "candidates": candidates,
        "limits": {
            "maxItems": limit,
            "truncated": len(candidates) >= limit,
            "fallbackUsed": fallback_used,
        },
        "usage": {
            "canSupportResumeFacts": any(
                not candidate["referenceOnly"] for candidate in candidates
            ),
            "requiresUserEvidence": True,
        },
    }


def _material_sources(
    *,
    prompt: str,
    job_brief: str,
    files: list[dict[str, Any]],
    hidden_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    has_reference_sources = bool(job_brief.strip()) or any(
        isinstance(file.get("content"), str) and file["content"].strip()
        for file in files[:5]
    )
    if prompt.strip() and _is_substantive_prompt_material(
        prompt,
        has_reference_sources=has_reference_sources,
    ):
        sources.append(
            {
                "sourceType": "prompt",
                "sourceIndex": 0,
                "allowFallback": True,
                "title": "Current prompt",
                "text": sanitize_agent_text(prompt, hidden_terms=hidden_terms),
            },
        )

    if job_brief.strip():
        sources.append(
            {
                "sourceType": "jobBrief",
                "sourceIndex": 0,
                "allowFallback": True,
                "referenceOnly": True,
                "title": "Job brief",
                "text": sanitize_agent_text(job_brief, hidden_terms=hidden_terms),
            },
        )

    for index, file in enumerate(files[:5], start=1):
        content = file.get("content")
        if not isinstance(content, str) or not content.strip():
            continue

        filename = str(file.get("filename") or f"Attachment {index}")
        sources.append(
            {
                "sourceType": "attachment",
                "sourceIndex": index,
                "allowFallback": True,
                "title": sanitize_agent_text(filename, hidden_terms=hidden_terms),
                "mediaType": str(file.get("mediaType") or ""),
                "text": sanitize_agent_text(content, hidden_terms=hidden_terms),
            },
        )

    return sources


def _material_candidates(
    sources: list[dict[str, Any]],
    *,
    focus: str,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in sources:
        source_reference_only = source.get("referenceOnly") is True
        for snippet in _candidate_snippets(str(source.get("text") or "")):
            sections = _suggested_sections(snippet)
            reference_only = source_reference_only or _is_reference_only(snippet)
            if not _matches_focus(focus, sections, reference_only):
                continue

            key = _duplicate_key(snippet)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                _candidate_payload(
                    source,
                    snippet,
                    sections=sections,
                    reference_only=reference_only,
                ),
            )
            if len(candidates) >= limit:
                return candidates

    return candidates


def _fallback_candidates(
    sources: list[dict[str, Any]],
    *,
    focus: str,
    limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for source in sources:
        if source.get("allowFallback") is not True:
            continue

        snippet = _first_non_empty_snippet(str(source.get("text") or ""))
        if not snippet:
            continue
        reference_only = source.get("referenceOnly") is True or _is_reference_only(
            snippet,
        )
        if focus == "resume_facts" and reference_only:
            continue
        candidates.append(
            _candidate_payload(
                source,
                snippet,
                sections=[],
                reference_only=reference_only,
            ),
        )
        if len(candidates) >= limit:
            break

    return candidates


def _candidate_payload(
    source: dict[str, Any],
    snippet: str,
    *,
    sections: list[str],
    reference_only: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "sourceType": source.get("sourceType"),
        "sourceIndex": source.get("sourceIndex"),
        "title": source.get("title"),
        "suggestedSections": sections,
        "referenceOnly": reference_only,
        "excerpt": _compact_excerpt(snippet),
    }
    media_type = source.get("mediaType")
    if media_type:
        payload["mediaType"] = media_type
    return payload


def _candidate_snippets(text: str) -> list[str]:
    fragments = [
        fragment.strip(" -•\t")
        for fragment in compiled_agent_pattern("material.splitter").split(text)
    ]
    snippets = [fragment for fragment in fragments if len(fragment) >= 8]
    if snippets:
        return snippets

    fallback = _first_non_empty_snippet(text)
    return [fallback] if fallback else []


def _first_non_empty_snippet(text: str) -> str:
    return next(
        (line.strip(" -•\t") for line in text.splitlines() if line.strip()),
        "",
    )


def _is_substantive_prompt_material(
    prompt: str,
    *,
    has_reference_sources: bool,
) -> bool:
    text = re.sub(r"\s+", " ", prompt).strip()
    if "\n" in prompt.strip():
        return True
    if re.search(r"[:：]", text) and len(text) >= 12:
        return True
    if len(text) >= 30:
        return True

    return not has_reference_sources and len(text) >= 24


def _suggested_sections(snippet: str) -> list[str]:
    return [
        section
        for section, pattern_name in SECTION_PATTERNS
        if matches_agent_pattern(snippet, pattern_name)
    ]


def _is_reference_only(snippet: str) -> bool:
    return matches_agent_pattern(snippet, "material.jd")


def _matches_focus(
    focus: str,
    sections: list[str],
    reference_only: bool,
) -> bool:
    if focus == "all":
        return bool(sections) or reference_only
    if focus == "resume_facts":
        return bool(sections) and not reference_only
    if focus == "jd":
        return reference_only

    expected_sections = FOCUS_SECTIONS.get(focus)
    return bool(expected_sections and expected_sections.intersection(sections))


def _bounded_max_items(value: int) -> int:
    if isinstance(value, bool):
        return DEFAULT_MATERIAL_CANDIDATES
    return min(MAX_MATERIAL_CANDIDATES, max(1, value))


def _compact_excerpt(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= MAX_MATERIAL_EXCERPT_CHARS:
        return text
    return f"{text[: MAX_MATERIAL_EXCERPT_CHARS - 3]}..."


def _duplicate_key(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())
