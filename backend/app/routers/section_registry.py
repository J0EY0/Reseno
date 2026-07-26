from fastapi import APIRouter

from app.schemas.common import ApiResponse, ok_response
from app.schemas.section_registry import (
    SectionRegistryEntryResponse,
    SectionRegistryResponse,
)
from app.services.agent.section_registry import SECTION_REGISTRY

router = APIRouter(prefix="/api/section-registry", tags=["section-registry"])


@router.get("", response_model=ApiResponse[SectionRegistryResponse])
def get_section_registry() -> ApiResponse[SectionRegistryResponse]:
    """Return the backend-owned resume section registry."""

    return ok_response(
        SectionRegistryResponse(
            sections=[
                SectionRegistryEntryResponse(
                    kind=section["kind"],
                    defaultLayout=section["defaultLayout"],
                    labels=section["labels"],
                    aliases=section["aliases"],
                )
                for section in SECTION_REGISTRY
            ],
        ),
    )
