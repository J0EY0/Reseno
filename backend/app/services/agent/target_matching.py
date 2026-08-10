from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from app.schemas.agent import AgentTargetContext
from app.services.agent.target_context import target_context_requirements

_LATIN_STOP_WORDS = {
    "about",
    "after",
    "also",
    "analyze",
    "and",
    "basic",
    "build",
    "can",
    "change",
    "changing",
    "description",
    "don",
    "dont",
    "edit",
    "following",
    "for",
    "from",
    "have",
    "information",
    "into",
    "job",
    "just",
    "match",
    "matching",
    "modify",
    "must",
    "needs",
    "not",
    "only",
    "optimize",
    "our",
    "personal",
    "platform",
    "please",
    "required",
    "requirement",
    "requirements",
    "responsibilities",
    "responsibility",
    "review",
    "rewrite",
    "resume",
    "role",
    "strong",
    "team",
    "tell",
    "that",
    "the",
    "their",
    "this",
    "update",
    "use",
    "what",
    "with",
    "without",
    "work",
    "you",
    "your",
}
_CJK_STOP_WORDS = {
    "以及",
    "了解",
    "优先",
    "使用",
    "具有",
    "具备",
    "参与",
    "协作",
    "岗位",
    "工作",
    "掌握",
    "开发经验",
    "经验",
    "熟悉",
    "相关",
    "能够",
    "良好",
    "负责",
    "进行",
    "需要",
    "项目",
}
_CJK_HEADERS = {
    "岗位要求",
    "岗位职责",
    "任职要求",
    "任职资格",
    "职位要求",
    "职位职责",
}
_CJK_INSTRUCTION_MARKERS = (
    "不要",
    "以下",
    "修改",
    "基础信息",
    "帮我",
    "根据",
    "简历",
    "请勿",
    "上述",
)
_CJK_REQUIREMENT_PREFIXES = ("熟悉", "具备", "掌握", "负责")
_CJK_REQUIREMENT_SUFFIXES = ("经验", "能力", "优先")
_CJK_REQUIREMENT_CONNECTORS = re.compile(r"[和与及、]")
_KEYWORD_ALIASES = {
    "accessibility": "accessibility",
    "accessible": "accessibility",
    "component": "component",
    "components": "component",
    "node-js": "node.js",
    "node.js": "node.js",
    "nodejs": "node.js",
    "react.js": "react",
    "reactjs": "react",
    "tailwindcss": "tailwind css",
    "ts": "typescript",
    "typescript": "typescript",
}
_KEYWORD_PHRASE_ALIASES = {
    "ci cd": "ci/cd",
    "node js": "node.js",
    "tailwind css": "tailwind css",
    "type script": "typescript",
}
_SHORT_TECH_KEYWORDS = frozenset({"ai", "c#", "go", "ml", "qa", "ui", "ux"})
_RESUME_METADATA_FIELDS = frozenset(
    {"basicfieldstatus", "id", "kind", "schemaversion", "title"},
)
_TOKEN_PATTERN = re.compile(
    r"[\u3400-\u9fff]+|[a-z0-9]+(?:\.[a-z0-9]+|[+#]+|-[a-z0-9]+)*",
)
_CJK_PATTERN = re.compile(r"^[\u3400-\u9fff]+$")


@dataclass(frozen=True, slots=True)
class TargetMatch:
    """Authoritative keyword coverage for one resume and target context."""

    score: int | None
    matched: tuple[str, ...]
    missing: tuple[str, ...]


def match_resume_to_target(
    resume: Mapping[str, object],
    context: AgentTargetContext | None,
) -> TargetMatch:
    """Compare structured target requirements with visible resume content."""

    target_texts = target_context_requirements(context)
    if context is not None and context.description.strip():
        target_texts.append(context.description)
    target_keywords = _extract_keywords(target_texts)
    if not target_keywords:
        return TargetMatch(score=None, matched=(), missing=())

    resume_texts = tuple(_iter_string_values(resume))
    resume_keywords = set(_extract_keywords(resume_texts))
    normalized_resume_texts = tuple(
        _normalize_match_text(text) for text in resume_texts
    )
    matched_values: list[str] = []
    missing_values: list[str] = []
    for keyword in target_keywords:
        destination = (
            matched_values
            if _keyword_matches_resume(
                keyword,
                resume_keywords,
                normalized_resume_texts,
            )
            else missing_values
        )
        destination.append(keyword)

    matched = tuple(matched_values)
    missing = tuple(missing_values)
    score = round(len(matched) / len(target_keywords) * 100)
    return TargetMatch(score=score, matched=matched, missing=missing)


def _extract_keywords(texts: Iterable[str]) -> tuple[str, ...]:
    keywords: list[str] = []
    seen: set[str] = set()

    for text in texts:
        tokens = _TOKEN_PATTERN.findall(_normalize_match_text(text))
        index = 0
        while index < len(tokens):
            token = tokens[index]
            phrase = " ".join(tokens[index : index + 2])
            phrase_alias = _KEYWORD_PHRASE_ALIASES.get(phrase)
            if phrase_alias is not None:
                _append_unique(keywords, seen, phrase_alias)
                index += 2
                continue

            if _CJK_PATTERN.fullmatch(token):
                for keyword in _cjk_requirement_keywords(token):
                    _append_unique(keywords, seen, keyword)
            else:
                keyword = _KEYWORD_ALIASES.get(token, token)
                if (
                    len(keyword) > 2 or keyword in _SHORT_TECH_KEYWORDS
                ) and keyword not in _LATIN_STOP_WORDS:
                    _append_unique(keywords, seen, keyword)
            index += 1

    return tuple(keywords)


def _normalize_match_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _keyword_matches_resume(
    keyword: str,
    resume_keywords: set[str],
    normalized_resume_texts: tuple[str, ...],
) -> bool:
    if keyword in resume_keywords:
        return True
    return (
        len(keyword) >= 2
        and _CJK_PATTERN.fullmatch(keyword) is not None
        and any(keyword in text for text in normalized_resume_texts)
    )


def _is_cjk_keyword(token: str) -> bool:
    return (
        len(token) >= 2
        and token not in _CJK_STOP_WORDS
        and token not in _CJK_HEADERS
        and not any(marker in token for marker in _CJK_INSTRUCTION_MARKERS)
    )


def _cjk_requirement_keywords(token: str) -> tuple[str, ...]:
    if not _is_cjk_keyword(token):
        return ()

    phrase = _strip_cjk_requirement_affixes(token)
    keywords: list[str] = []
    seen: set[str] = set()
    for part in _CJK_REQUIREMENT_CONNECTORS.split(phrase):
        keyword = _strip_cjk_requirement_affixes(part)
        if _is_cjk_keyword(keyword):
            _append_unique(keywords, seen, keyword)
    return tuple(keywords)


def _strip_cjk_requirement_affixes(value: str) -> str:
    result = value
    for prefix in _CJK_REQUIREMENT_PREFIXES:
        if result.startswith(prefix):
            result = result.removeprefix(prefix)
            break
    for suffix in _CJK_REQUIREMENT_SUFFIXES:
        if result.endswith(suffix):
            result = result.removesuffix(suffix)
            break
    return result


def _append_unique(values: list[str], seen: set[str], value: str) -> None:
    if value in seen:
        return
    seen.add(value)
    values.append(value)


def _iter_string_values(value: object) -> Iterator[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(key, str) and key.casefold() in _RESUME_METADATA_FIELDS:
                continue
            yield from _iter_string_values(item)
        return
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from _iter_string_values(item)
