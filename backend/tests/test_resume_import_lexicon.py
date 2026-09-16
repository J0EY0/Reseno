import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.resume_import_lexicon import (
    RESUME_IMPORT_LEXICON,
    load_resume_import_lexicon,
)


def _locale_payload(
    *,
    document_title_terms: list[str] | None = None,
    current_period_terms: list[str] | None = None,
) -> dict[str, list[str]]:
    return {
        "documentTitleTerms": document_title_terms or [],
        "currentPeriodTerms": current_period_terms or [],
        "dateRangeTerms": [],
        "datePartSeparators": [],
        "datePartSuffixes": [],
        "monthNames": [],
    }


def _write_lexicon(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "resume_import_lexicon.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def test_resume_import_lexicon_matches_parser_contract() -> None:
    locales = RESUME_IMPORT_LEXICON.locales

    assert locales["en"].document_title_terms == [
        "resume",
        "résumé",
        "cv",
        "curriculum vitae",
        "curriculum",
        "vitae",
    ]
    assert locales["zh"].document_title_terms == [
        "简历",
        "个人简历",
        "簡歷",
        "個人簡歷",
        "履歷",
        "個人履歷",
    ]
    assert locales["en"].current_period_terms == ["present", "current"]
    assert locales["zh"].current_period_terms == ["至今", "今", "现在", "現在"]
    assert locales["en"].date_range_terms == ["to"]
    assert locales["zh"].date_range_terms == ["至", "到"]
    assert locales["zh"].date_part_separators == ["年"]
    assert locales["zh"].date_part_suffixes == ["月"]
    assert {"January", "Jan", "September", "Sep", "Sept", "December", "Dec"} <= set(
        locales["en"].month_names
    )
    assert locales["zh"].month_names == []

    for locale in locales.values():
        for terms in (
            locale.document_title_terms,
            locale.current_period_terms,
            locale.date_range_terms,
            locale.date_part_separators,
            locale.date_part_suffixes,
            locale.month_names,
        ):
            assert all(term.strip() for term in terms)


@pytest.mark.parametrize(
    "payload",
    [
        {"locales": {}},
        {
            "locales": {
                "en": {
                    **_locale_payload(
                        document_title_terms=["resume"],
                        current_period_terms=["present"],
                    ),
                    "monthNames": [" "],
                },
            },
        },
        {
            "locales": {
                "en": _locale_payload(
                    document_title_terms=[" "],
                    current_period_terms=["present"],
                ),
                "zh": _locale_payload(),
            },
        },
        {
            "locales": {
                "en": {
                    **_locale_payload(current_period_terms=["present"]),
                    "documentTitleTerms": "resume",
                },
                "zh": _locale_payload(),
            },
        },
        {
            "locales": {
                "en": _locale_payload(current_period_terms=["present"]),
                "zh": _locale_payload(),
            },
        },
        {
            "locales": {
                "en": _locale_payload(document_title_terms=["resume"]),
                "zh": _locale_payload(),
            },
        },
    ],
)
def test_resume_import_lexicon_rejects_invalid_contract(
    tmp_path: Path,
    payload: object,
) -> None:
    path = _write_lexicon(tmp_path, payload)

    with pytest.raises(ValueError):
        load_resume_import_lexicon(path)


def test_resume_import_lexicon_locales_are_independent_from_agent_locales(
    tmp_path: Path,
) -> None:
    path = _write_lexicon(
        tmp_path,
        {
            "locales": {
                "fr": _locale_payload(
                    document_title_terms=["curriculum vitae"],
                    current_period_terms=["présent"],
                ),
            },
        },
    )

    assert set(load_resume_import_lexicon(path).locales) == {"fr"}


def test_resume_import_lexicon_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "resume_import_lexicon.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain valid JSON"):
        load_resume_import_lexicon(path)


def test_resume_import_lexicon_api_uses_standard_response(
    client: TestClient,
) -> None:
    response = client.get("/api/resume-import-lexicon")

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "message": "OK",
        "data": RESUME_IMPORT_LEXICON.model_dump(by_alias=True),
        "requestId": None,
    }
