from typing import Any, cast

RESUME_DOCUMENT_INVALID = "RESUME_DOCUMENT_INVALID"
RESUME_LIST_ITEM_CONTENT_INVALID = "RESUME_LIST_ITEM_CONTENT_INVALID"

_LIST_ITEM_EMPTY_STRING_FIELDS = ("meta", "period", "description")


class ResumeDocumentContractError(ValueError):
    """Describe one stable resume-document invariant violation."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path


def validate_resume_document(value: Any) -> dict[str, Any]:
    """Validate the canonical resume shape shared by every write producer."""

    if not isinstance(value, dict):
        raise ResumeDocumentContractError(RESUME_DOCUMENT_INVALID, "resume")

    if not isinstance(value.get("basic"), dict) or not isinstance(
        value.get("sections"),
        list,
    ):
        raise ResumeDocumentContractError(RESUME_DOCUMENT_INVALID, "resume")

    for section_index, section in enumerate(value["sections"]):
        section_path = f"resume.sections.{section_index}"
        if not isinstance(section, dict):
            raise ResumeDocumentContractError(
                RESUME_DOCUMENT_INVALID,
                section_path,
            )

        if section.get("layout") != "list":
            continue

        items = section.get("items")
        if not isinstance(items, list):
            raise ResumeDocumentContractError(
                RESUME_DOCUMENT_INVALID,
                f"{section_path}.items",
            )

        for item_index, item in enumerate(items):
            item_path = f"{section_path}.items.{item_index}"
            if not isinstance(item, dict):
                raise ResumeDocumentContractError(
                    RESUME_DOCUMENT_INVALID,
                    item_path,
                )

            if not isinstance(item.get("title"), str) or not isinstance(
                item.get("subtitle"),
                str,
            ):
                raise ResumeDocumentContractError(
                    RESUME_DOCUMENT_INVALID,
                    item_path,
                )

            if any(
                item.get(field) != "" for field in _LIST_ITEM_EMPTY_STRING_FIELDS
            ) or item.get("highlights") != []:
                raise ResumeDocumentContractError(
                    RESUME_LIST_ITEM_CONTENT_INVALID,
                    item_path,
                )

    return cast(dict[str, Any], value)
