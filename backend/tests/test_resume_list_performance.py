import json
from collections import OrderedDict
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.services import resumes


def test_unchanged_list_snapshots_do_not_repeat_document_validation(
    client, monkeypatch
):
    created = resumes.create_resume({"documentLocale": "en"})
    validate = Mock(wraps=resumes._ensure_resume_document)
    monkeypatch.setattr(resumes, "_ensure_resume_document", validate)

    first = resumes.list_resumes().model_dump(mode="json", by_alias=True)
    assert validate.call_count == 1
    second = resumes.list_resumes().model_dump(mode="json", by_alias=True)
    assert second == first
    assert validate.call_count == 1

    first["resumes"][0]["resume"]["basic"]["name"] = "Caller mutation"
    assert resumes.list_resumes().model_dump(mode="json", by_alias=True) == second
    assert second["resumes"][0]["id"] == created["resume"]["id"]


def test_changed_version_is_validated_and_missing_storage_still_fails(
    client, monkeypatch
):
    created = resumes.create_resume({"documentLocale": "en"})
    resume_id = created["resume"]["id"]
    resumes.list_resumes()
    saved = resumes.save_resume(
        resume_id, {**created["resume"], "title": "Updated"}, save_mode="autosave"
    )
    validate = Mock(wraps=resumes._ensure_resume_document)
    monkeypatch.setattr(resumes, "_ensure_resume_document", validate)

    assert resumes.list_resumes().resumes[0].title == "Updated"
    assert validate.call_count == 1
    assert resumes.list_resumes().resumes[0].title == "Updated"
    assert validate.call_count == 1

    path = resumes._resume_version_path(resume_id, int(saved["versionId"]))
    path.unlink()
    with pytest.raises(HTTPException) as error:
        resumes.list_resumes()
    assert error.value.status_code == 500
    assert error.value.detail == "RESUME_VERSION_STORAGE_MISSING"


@pytest.mark.parametrize("invalidity", ["unknown", "section-id", "item-id"])
def test_invalid_file_changes_are_never_hidden_or_remembered(
    client, monkeypatch, invalidity
):
    created = resumes.create_resume({"documentLocale": "en"})
    resumes.list_resumes()
    path = resumes._resume_version_path(created["resume"]["id"], 1)
    original = path.read_bytes()
    invalid = json.loads(original)
    if invalidity == "unknown":
        invalid["resume"]["basic"]["unknownField"] = "invalid"
        expected = "RESUME_DOCUMENT_INVALID"
    else:
        first, second = invalid["resume"]["sections"][:2]
        if invalidity == "section-id":
            second["id"] = first["id"]
        else:
            second["items"][0]["id"] = first["items"][0]["id"]
        expected = "RESUME_DOCUMENT_DUPLICATE_ID"
    path.write_text(json.dumps(invalid))
    validate = Mock(wraps=resumes._ensure_resume_document)
    monkeypatch.setattr(resumes, "_ensure_resume_document", validate)

    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            resumes.list_resumes()
        assert error.value.detail == expected
    assert validate.call_count == 2
    path.write_bytes(original)
    assert resumes.list_resumes().resumes[0].id == created["resume"]["id"]


def test_validation_cache_is_bounded_and_retains_only_digests(client, monkeypatch):
    monkeypatch.setattr(resumes, "_MAX_VALIDATED_SNAPSHOTS", 2)
    monkeypatch.setattr(resumes, "_VALIDATED_SNAPSHOTS", OrderedDict())
    created = resumes.create_resume({"documentLocale": "en"})
    path: Path = resumes._resume_version_path(created["resume"]["id"], 1)
    initial = path.read_bytes()
    payload = json.loads(initial)
    contents = [initial]
    for title in ("Second", "Third"):
        contents.append(json.dumps({**payload, "title": title}).encode())

    validate = Mock(wraps=resumes._ensure_resume_document)
    monkeypatch.setattr(resumes, "_ensure_resume_document", validate)
    for content in contents:
        resumes._parse_resume_bytes(content)
    assert validate.call_count == 3
    assert len(resumes._VALIDATED_SNAPSHOTS) == 2
    assert all(
        isinstance(key, bytes) and len(key) == 32 and value is None
        for key, value in resumes._VALIDATED_SNAPSHOTS.items()
    )
    resumes._parse_resume_bytes(contents[-1])
    assert validate.call_count == 3
    resumes._parse_resume_bytes(initial)
    assert validate.call_count == 4


def test_invalid_storage_directory_keeps_the_missing_snapshot_error(client):
    created = resumes.create_resume({"documentLocale": "en"})
    resumes.list_resumes()
    path = resumes._resume_version_path(created["resume"]["id"], 1)
    path.unlink()
    path.parent.rmdir()
    path.parent.write_bytes(b"invalid directory")

    with pytest.raises(HTTPException) as error:
        resumes.list_resumes()
    assert error.value.status_code == 500
    assert error.value.detail == "RESUME_VERSION_STORAGE_MISSING"
