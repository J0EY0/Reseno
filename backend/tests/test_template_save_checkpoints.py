import json

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import templates
from tests.template_fixtures import portable_template


def _create(client: TestClient) -> dict:
    response = client.post(
        "/api/templates", json={"template": portable_template("Explicit")}
    )
    assert response.status_code == 200
    return response.json()["data"]["template"]


def _update(client: TestClient, template_id: str, name: str, mode: str) -> dict:
    response = client.put(
        f"/api/templates/{template_id}",
        json={"template": portable_template(name), "saveMode": mode},
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_autosaves_preserve_one_explicit_checkpoint_and_discard_restores_it(
    client: TestClient,
) -> None:
    created = _create(client)
    template_id = created["id"]
    for name in ("First draft", "Second draft"):
        saved = _update(client, template_id, name, "autosave")
        assert saved["template"]["name"] == name
        assert saved["checkpoint"] == created
        detail = client.get(f"/api/templates/{template_id}").json()["data"]
        assert detail == saved
        assert "_checkpoint" not in saved["template"]
    catalog = client.get("/api/templates").json()["data"]["templates"]
    assert (
        next(item for item in catalog if item["id"] == template_id)["name"]
        == "Second draft"
    )
    assert all("_checkpoint" not in item for item in catalog)
    restored = client.post(f"/api/templates/{template_id}/discard").json()["data"]
    assert restored["checkpoint"] is None
    assert restored["template"]["name"] == "Explicit"
    assert restored["template"]["updatedAt"] > saved["template"]["updatedAt"]
    path = get_settings().storage_dir / "templates" / template_id / "current.json"
    assert "_checkpoint" not in json.loads(path.read_text())


def test_manual_save_promotes_autosaved_content_and_starts_next_checkpoint(
    client: TestClient,
) -> None:
    template_id = _create(client)["id"]
    _update(client, template_id, "Confirmed draft", "autosave")
    confirmed = _update(client, template_id, "Confirmed draft", "checkpoint")
    assert confirmed["checkpoint"] is None
    draft = _update(client, template_id, "Later draft", "autosave")
    assert draft["checkpoint"] == confirmed["template"]
    restored = client.post(f"/api/templates/{template_id}/discard").json()["data"]
    assert restored["template"]["name"] == "Confirmed draft"


@pytest.mark.parametrize("operation", ["autosave", "checkpoint", "discard"])
def test_failed_checkpoint_publication_restores_current_and_explicit_snapshot(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    template_id = _create(client)["id"]
    saved = _update(client, template_id, "Draft before failure", "autosave")
    path = get_settings().storage_dir / "templates" / template_id / "current.json"
    original_bytes = path.read_bytes()
    original_write = templates._write_template_json

    def fail_after_publication(entity_id: str, content: dict) -> None:
        original_write(entity_id, content)
        raise OSError("Forced checkpoint publication failure")

    monkeypatch.setattr(templates, "_write_template_json", fail_after_publication)
    with pytest.raises(OSError, match="Forced checkpoint publication failure"):
        if operation == "discard":
            templates.discard_template_changes(template_id)
        else:
            templates.update_template(
                template_id, portable_template("Failed update"), save_mode=operation
            )
    assert path.read_bytes() == original_bytes
    assert client.get(f"/api/templates/{template_id}").json()["data"] == saved
