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
                    kind=str(section["kind"]),
                    defaultLayout=str(section["defaultLayout"]),
                    labels=dict(section["labels"]),
                    aliases=[
                        alias
                        for alias in section.get("aliases", [])
                        if isinstance(alias, str) and alias
                    ],
                )
                for section in SECTION_REGISTRY
            ],
        ),
    )
