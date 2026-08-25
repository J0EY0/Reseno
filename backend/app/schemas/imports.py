from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)
from pydantic_core import PydanticCustomError

JsonObject = dict[str, Any]
BuiltinTemplateId = Literal[
    "minimal",
    "modern",
    "compact",
    "classic",
    "executive",
    "academic",
]
BUILTIN_TEMPLATE_IDS = frozenset(
    {"minimal", "modern", "compact", "classic", "executive", "academic"}
)
HexColor = str


class ArtifactModel(BaseModel):
    """Reject fields that do not belong to the public artifact contract."""

    model_config = ConfigDict(extra="forbid", strict=True)


class TypographySettings(ArtifactModel):
    font_family: Literal["inter", "noto_sans_sc", "serif", "plex"] = Field(
        alias="fontFamily"
    )
    font_size: Literal[12, 14, 16, 18, 20] = Field(alias="fontSize")


class TemplateSettings(ArtifactModel):
    page_padding_top: float = Field(alias="pagePaddingTop", ge=8, le=20)
    page_padding_x: float = Field(alias="pagePaddingX", ge=8, le=18)
    page_padding_bottom: float = Field(alias="pagePaddingBottom", ge=8, le=18)
    section_gap: float = Field(alias="sectionGap", ge=0.8, le=2.4)
    item_gap: float = Field(alias="itemGap", ge=0.4, le=1.8)
    body_line_height: float = Field(alias="bodyLineHeight", ge=1.4, le=2.2)
    name_scale: float = Field(alias="nameScale", ge=1.6, le=2.8)
    section_title_scale: float = Field(alias="sectionTitleScale", ge=0.75, le=1.6)
    item_title_scale: float = Field(alias="itemTitleScale", ge=0.85, le=1.4)
    meta_scale: float = Field(alias="metaScale", ge=0.75, le=1.15)
    body_scale: float = Field(alias="bodyScale", ge=0.85, le=1.2)
    page_background: HexColor = Field(
        alias="pageBackground", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    surface_color: HexColor = Field(alias="surfaceColor", pattern=r"^#[0-9a-fA-F]{6}$")
    heading_color: HexColor = Field(alias="headingColor", pattern=r"^#[0-9a-fA-F]{6}$")
    body_color: HexColor = Field(alias="bodyColor", pattern=r"^#[0-9a-fA-F]{6}$")
    muted_color: HexColor = Field(alias="mutedColor", pattern=r"^#[0-9a-fA-F]{6}$")
    divider_color: HexColor = Field(alias="dividerColor", pattern=r"^#[0-9a-fA-F]{6}$")
    divider_thickness: float = Field(alias="dividerThickness", ge=0.5, le=3)


class TemplateSettingsOverrides(ArtifactModel):
    """Sparse resume-level overrides applied over a template's defaults."""

    page_padding_top: float | None = Field(
        default=None, alias="pagePaddingTop", ge=8, le=20
    )
    page_padding_x: float | None = Field(
        default=None, alias="pagePaddingX", ge=8, le=18
    )
    page_padding_bottom: float | None = Field(
        default=None, alias="pagePaddingBottom", ge=8, le=18
    )
    section_gap: float | None = Field(default=None, alias="sectionGap", ge=0.8, le=2.4)
    item_gap: float | None = Field(default=None, alias="itemGap", ge=0.4, le=1.8)
    body_line_height: float | None = Field(
        default=None, alias="bodyLineHeight", ge=1.4, le=2.2
    )
    name_scale: float | None = Field(default=None, alias="nameScale", ge=1.6, le=2.8)
    section_title_scale: float | None = Field(
        default=None, alias="sectionTitleScale", ge=0.75, le=1.6
    )
    item_title_scale: float | None = Field(
        default=None, alias="itemTitleScale", ge=0.85, le=1.4
    )
    meta_scale: float | None = Field(default=None, alias="metaScale", ge=0.75, le=1.15)
    body_scale: float | None = Field(default=None, alias="bodyScale", ge=0.85, le=1.2)
    page_background: HexColor | None = Field(
        default=None, alias="pageBackground", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    surface_color: HexColor | None = Field(
        default=None, alias="surfaceColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    heading_color: HexColor | None = Field(
        default=None, alias="headingColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    body_color: HexColor | None = Field(
        default=None, alias="bodyColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    muted_color: HexColor | None = Field(
        default=None, alias="mutedColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    divider_color: HexColor | None = Field(
        default=None, alias="dividerColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    divider_thickness: float | None = Field(
        default=None, alias="dividerThickness", ge=0.5, le=3
    )

    @model_validator(mode="after")
    def reject_explicit_nulls(self) -> "TemplateSettingsOverrides":
        if any(
            getattr(self, field_name) is None for field_name in self.model_fields_set
        ):
            raise ValueError("Template setting overrides cannot be null.")
        return self

    @model_serializer(mode="wrap")
    def serialize_sparse(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, Any]:
        return {key: value for key, value in handler(self).items() if value is not None}


class TemplateImageElement(ArtifactModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    src: str = Field(pattern=r"^(?:$|data:image/)")
    alt: str
    x: float = Field(ge=0, le=210)
    y: float = Field(ge=0, le=297)
    width: float = Field(ge=6, le=120)
    height: float = Field(ge=6, le=120)
    opacity: float = Field(ge=0.05, le=1)
    border_width: float = Field(alias="borderWidth", ge=0, le=8)
    border_color: HexColor = Field(alias="borderColor", pattern=r"^#[0-9a-fA-F]{6}$")
    border_radius: float = Field(alias="borderRadius", ge=0, le=32)
    object_fit: Literal["contain", "cover"] = Field(alias="objectFit")
    visible: bool

    @model_validator(mode="after")
    def validate_page_bounds(self) -> "TemplateImageElement":
        if self.x + self.width > 210:
            raise PydanticCustomError(
                "template_image_out_of_bounds",
                "Template image must fit within the A4 page width.",
            )
        if self.y + self.height > 297:
            raise PydanticCustomError(
                "template_image_out_of_bounds",
                "Template image must fit within the A4 page height.",
            )
        return self


class TemplateLayout(ArtifactModel):
    basic_info: Literal["centered", "left", "split", "profile", "sidebar"] = Field(
        alias="basicInfo"
    )
    section: Literal["ruled", "boxed", "accent", "plain", "band"]
    timeline_item_layout: Literal["split", "stacked", "compact"] = Field(
        alias="timelineItemLayout"
    )
    list_item_layout: Literal["list", "inline", "columns"] = Field(
        alias="listItemLayout"
    )
    avatar_position: Literal["none", "right", "left", "center"] = Field(
        alias="avatarPosition"
    )
    avatar_shape: Literal["rounded", "circle", "square"] = Field(alias="avatarShape")
    avatar_width: float = Field(alias="avatarWidth", ge=16, le=48)
    avatar_height: float = Field(alias="avatarHeight", ge=16, le=56)
    avatar_offset_x: float = Field(alias="avatarOffsetX", ge=-40, le=40)
    avatar_offset_y: float = Field(alias="avatarOffsetY", ge=-40, le=40)
    avatar_border_width: float = Field(alias="avatarBorderWidth", ge=0, le=8)
    avatar_border_color: HexColor = Field(
        alias="avatarBorderColor", pattern=r"^#[0-9a-fA-F]{6}$"
    )
    images: list[TemplateImageElement]

    @model_validator(mode="after")
    def validate_unique_image_ids(self) -> "TemplateLayout":
        image_ids = [image.id for image in self.images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("Template image ids must be unique.")
        return self


class ResumeArtifactItem(ArtifactModel):
    """Portable resume content without backend-owned identity metadata."""

    title: str = Field(min_length=1, max_length=50)
    resume: JsonObject
    job_brief: str = Field(alias="jobBrief")
    typography: TypographySettings
    template: str = Field(min_length=1)
    template_settings: TemplateSettingsOverrides | None = Field(
        alias="templateSettings"
    )


class TemplateArtifactItem(ArtifactModel):
    """Portable template content without backend-owned identity metadata."""

    preset: BuiltinTemplateId
    name: str = Field(min_length=1)
    description: str
    layout: TemplateLayout
    typography: TypographySettings
    settings: TemplateSettings


class EmbeddedTemplate(ArtifactModel):
    """An artifact-local custom template referenced by one or more resumes."""

    ref: str = Field(pattern=r"^custom:(?:0|[1-9][0-9]*)$")
    definition: TemplateArtifactItem


class ResumeArtifactV1(ArtifactModel):
    """The only supported JSON resume import format."""

    format: Literal["resumate.resume"]
    format_version: Literal[1] = Field(alias="formatVersion")
    templates: list[EmbeddedTemplate]
    resumes: list[ResumeArtifactItem] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_template_references(self) -> "ResumeArtifactV1":
        refs = [template.ref for template in self.templates]
        if len(refs) != len(set(refs)):
            raise ValueError("Embedded template references must be unique.")

        embedded_refs = set(refs)
        referenced_custom_templates = {
            resume.template
            for resume in self.resumes
            if resume.template not in BUILTIN_TEMPLATE_IDS
        }
        if referenced_custom_templates != embedded_refs:
            raise ValueError(
                "Every custom template must be declared and referenced exactly by id."
            )
        return self


class TemplateArtifactV1(ArtifactModel):
    """The only supported JSON template import format."""

    format: Literal["resumate.template"]
    format_version: Literal[1] = Field(alias="formatVersion")
    templates: list[TemplateArtifactItem] = Field(min_length=1)


class ImportResumeResponse(BaseModel):
    """Resume items extracted from an uploaded JSON file."""

    templates: list[EmbeddedTemplate]
    resumes: list[ResumeArtifactItem]


class ImportTemplatesResponse(BaseModel):
    """Template items extracted from an uploaded JSON file."""

    templates: list[TemplateArtifactItem]
