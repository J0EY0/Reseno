from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SectionLayout = Literal["timeline", "list"]


class SectionRegistryEntryResponse(BaseModel):
    """One resume section definition owned by the backend registry."""

    model_config = ConfigDict(populate_by_name=True)

    kind: str
    default_layout: SectionLayout = Field(alias="defaultLayout")
    labels: dict[str, str]
    aliases: list[str]


class SectionRegistryResponse(BaseModel):
    """Section registry used by agent tools and client-side import parsing."""

    sections: list[SectionRegistryEntryResponse]
