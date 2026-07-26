import json
from pathlib import Path

from pydantic import ValidationError

from app.schemas.resume_import_lexicon import ResumeImportLexiconResponse

RESUME_IMPORT_LEXICON_PATH = Path(__file__).with_name("resume_import_lexicon.json")


def load_resume_import_lexicon(
    path: Path = RESUME_IMPORT_LEXICON_PATH,
) -> ResumeImportLexiconResponse:
    """Read and validate the backend-owned resume import lexicon."""

    try:
        raw_payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to read {path.name}.") from exc

    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} must contain valid JSON.") from exc

    try:
        return ResumeImportLexiconResponse.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(
            f"{path.name} does not match the resume import lexicon contract."
        ) from exc


RESUME_IMPORT_LEXICON = load_resume_import_lexicon()
