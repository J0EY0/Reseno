import secrets
from typing import Any

from app.document_locales import DocumentLocale
from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
)

LocalizedTitle = dict[DocumentLocale, str]
SectionSpec = tuple[str, LocalizedTitle]

_STARTER_SECTIONS: dict[str, tuple[SectionSpec, ...]] = {
    "earlyCareer": (
        ("education", {"zh": "", "en": ""}),
        ("experience", {"zh": "实习经历", "en": "Internship Experience"}),
        ("project", {"zh": "项目经历", "en": "Projects"}),
        ("achievement", {"zh": "荣誉奖项", "en": "Awards"}),
        ("simple_list", {"zh": "技能", "en": "Skills"}),
    ),
    "experienced": (
        ("experience", {"zh": "工作经历", "en": "Experience"}),
        ("project", {"zh": "代表项目", "en": "Selected Project"}),
        ("achievement", {"zh": "专业认证", "en": "Certification"}),
        ("simple_list", {"zh": "核心技能", "en": "Core Skills"}),
        ("education", {"zh": "", "en": ""}),
    ),
    "executive": (
        ("experience", {"zh": "高管经历", "en": "Executive Experience"}),
        ("project", {"zh": "代表性转型项目", "en": "Selected Transformation"}),
        ("achievement", {"zh": "董事会与行业参与", "en": "Board & Advisory"}),
        ("simple_list", {"zh": "领导力能力", "en": "Leadership Capabilities"}),
        ("education", {"zh": "", "en": ""}),
    ),
    "research": (
        ("education", {"zh": "", "en": ""}),
        ("experience", {"zh": "研究经历", "en": "Research Experience"}),
        ("publication", {"zh": "代表性论文", "en": "Selected Publications"}),
        ("experience", {"zh": "教学经历", "en": "Teaching Experience"}),
        ("achievement", {"zh": "荣誉与资助", "en": "Honors & Grants"}),
        ("simple_list", {"zh": "研究技能", "en": "Research Skills"}),
    ),
}


def _generate_document_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


def _create_empty_item(kind: str) -> dict[str, Any]:
    return {
        "id": _generate_document_id("item"),
        **{field: "" for field in ITEM_STRING_FIELDS_BY_KIND[kind]},
        **{field: [] for field in ITEM_LIST_FIELDS_BY_KIND[kind]},
    }


def create_empty_resume(
    starter_id: str,
    document_locale: DocumentLocale,
) -> dict[str, Any]:
    """Create one blank canonical document from a product starter."""

    sections = [
        {
            "id": _generate_document_id("section"),
            "kind": kind,
            "title": titles[document_locale],
            "items": [_create_empty_item(kind)],
        }
        for kind, titles in _STARTER_SECTIONS[starter_id]
    ]
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "",
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": sections,
    }
