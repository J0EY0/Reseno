from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok_response
from app.schemas.resume_import_lexicon import ResumeImportLexiconResponse
from app.services.resume_import_lexicon import RESUME_IMPORT_LEXICON

router = APIRouter(
    prefix="/api/resume-import-lexicon",
    tags=["resume-import-lexicon"],
)


@router.get("", response_model=ApiResponse[ResumeImportLexiconResponse])
def get_resume_import_lexicon() -> ApiResponse[ResumeImportLexiconResponse]:
    """Return language terms used by PDF resume import parsing."""

    return ok_response(RESUME_IMPORT_LEXICON)
