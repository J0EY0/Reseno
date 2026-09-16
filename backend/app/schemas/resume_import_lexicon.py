from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ResumeImportLocaleLexiconResponse(BaseModel):
    """Language-specific terms used while parsing imported resumes."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        strict=True,
    )

    document_title_terms: list[str] = Field(alias="documentTitleTerms")
    current_period_terms: list[str] = Field(alias="currentPeriodTerms")
    date_range_terms: list[str] = Field(alias="dateRangeTerms")
    date_part_separators: list[str] = Field(alias="datePartSeparators")
    date_part_suffixes: list[str] = Field(alias="datePartSuffixes")
    month_names: list[str] = Field(alias="monthNames")

    @field_validator(
        "document_title_terms",
        "current_period_terms",
        "date_range_terms",
        "date_part_separators",
        "date_part_suffixes",
        "month_names",
    )
    @classmethod
    def validate_non_empty_terms(cls, terms: list[str]) -> list[str]:
        if any(not term.strip() for term in terms):
            raise ValueError("Resume import lexicon terms must not be empty.")
        return terms


class ResumeImportLexiconResponse(BaseModel):
    """Backend-owned multilingual lexicon for PDF resume import."""

    model_config = ConfigDict(extra="forbid", strict=True)

    locales: dict[str, ResumeImportLocaleLexiconResponse]

    @model_validator(mode="after")
    def validate_locale_contract(self) -> Self:
        if not self.locales:
            raise ValueError("Resume import lexicon must define locales.")

        invalid_locale_names = [locale for locale in self.locales if not locale.strip()]
        if invalid_locale_names:
            raise ValueError("Resume import locale names must not be empty.")

        # Individual locales may omit a term category, but the merged lexicon
        # must still protect document titles and recognize open-ended periods.
        if not any(locale.document_title_terms for locale in self.locales.values()):
            raise ValueError("Resume import lexicon must define document title terms.")
        if not any(locale.current_period_terms for locale in self.locales.values()):
            raise ValueError("Resume import lexicon must define current period terms.")

        return self
