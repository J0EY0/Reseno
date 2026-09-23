import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services.resume_starters import create_empty_resume
from tests.template_fixtures import portable_template


def _template() -> dict:
    template = portable_template("Section layouts")
    template["layout"]["timelineItemLayout"] = "inline"
    template["layout"]["sectionItemLayouts"] = {
        "education": "inline",
        "experience": "compact",
        "project": "stacked",
        "publication": "split",
        "achievement": "inline",
    }
    return template


def _create(client: TestClient, template: dict) -> dict:
    response = client.post("/api/templates", json={"template": template})
    assert response.status_code == 200
    return response.json()["data"]["template"]


def _detail(client: TestClient, template_id: str) -> dict:
    response = client.get(f"/api/templates/{template_id}")
    assert response.status_code == 200
    return response.json()["data"]


def test_missing_section_layouts_defaults_to_global_without_materializing_kinds(
    client: TestClient,
) -> None:
    template = _template()
    del template["layout"]["sectionItemLayouts"]
    created = _create(client, template)
    layout = _detail(client, created["id"])["template"]["layout"]

    assert layout["timelineItemLayout"] == "inline"
    assert layout["sectionItemLayouts"] == {}
    assert layout["listItemLayout"] == template["layout"]["listItemLayout"]


def test_section_layouts_survive_storage_and_copy_without_sharing_edits(
    client: TestClient,
) -> None:
    template = _template()
    created = _create(client, template)
    loaded = _detail(client, created["id"])["template"]
    assert {key: loaded[key] for key in template} == template
    path = get_settings().storage_dir / "templates" / created["id"] / "current.json"
    assert json.loads(path.read_text())["layout"] == template["layout"]

    copied_payload = {key: loaded[key] for key in template}
    copied_payload["name"] = "Section layouts copy"
    copied = _create(client, copied_payload)
    assert copied["id"] != created["id"]
    assert _detail(client, copied["id"])["template"]["layout"] == template["layout"]

    copied_payload["layout"]["sectionItemLayouts"] = {}
    updated = client.put(
        f"/api/templates/{copied['id']}", json={"template": copied_payload}
    )
    assert updated.status_code == 200
    assert (
        _detail(client, copied["id"])["template"]["layout"]["sectionItemLayouts"] == {}
    )
    assert _detail(client, created["id"])["template"]["layout"] == template["layout"]


def test_section_layout_checkpoint_restores_overrides_and_promotes_removed_keys(
    client: TestClient,
) -> None:
    template = _template()
    created = _create(client, template)
    template_id = created["id"]
    draft = deepcopy(template)
    draft["layout"]["timelineItemLayout"] = "stacked"
    draft["layout"]["sectionItemLayouts"] = {"project": "compact"}

    autosaved = client.put(
        f"/api/templates/{template_id}",
        json={"template": draft, "saveMode": "autosave"},
    )
    assert autosaved.status_code == 200
    pending = _detail(client, template_id)
    assert pending["template"]["layout"] == draft["layout"]
    assert pending["checkpoint"]["layout"] == template["layout"]

    discarded = client.post(f"/api/templates/{template_id}/discard")
    assert discarded.status_code == 200
    restored = _detail(client, template_id)
    assert restored["template"]["layout"] == template["layout"]
    assert restored["checkpoint"] is None

    confirmed = client.put(
        f"/api/templates/{template_id}",
        json={"template": draft, "saveMode": "checkpoint"},
    )
    assert confirmed.status_code == 200
    saved = _detail(client, template_id)
    assert saved["template"]["layout"] == draft["layout"]
    assert saved["checkpoint"] is None


@pytest.mark.parametrize("artifact_kind", ["templates", "resume"])
def test_section_layouts_round_trip_through_portable_artifacts(
    client: TestClient, artifact_kind: str
) -> None:
    template = _template()
    saved = _create(client, template)
    loaded = _detail(client, saved["id"])["template"]
    definition = {key: loaded[key] for key in template}
    if artifact_kind == "templates":
        artifact = {
            "format": "reseno.template",
            "formatVersion": 1,
            "templates": [definition],
        }
    else:
        artifact = {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [{"ref": "custom:0", "definition": definition}],
            "resumes": [
                {
                    "title": "Section layout resume",
                    "documentLocale": "en",
                    "resume": create_empty_resume("earlyCareer", "en"),
                    "jobBrief": "",
                    "typography": template["typography"],
                    "template": "custom:0",
                    "templateSettings": None,
                }
            ],
        }
    imported = client.post(
        f"/api/import/{artifact_kind}",
        files={"file": ("artifact.json", json.dumps(artifact), "application/json")},
    )
    assert imported.status_code == 200
    data = imported.json()["data"]
    assert data == {
        key: value
        for key, value in artifact.items()
        if key not in {"format", "formatVersion"}
    }
    imported_template = data["templates"][0]
    if artifact_kind == "resume":
        imported_template = imported_template["definition"]
    restored = _create(client, imported_template)
    assert _detail(client, restored["id"])["template"]["layout"] == template["layout"]


@pytest.mark.parametrize(
    "invalid_layout",
    [
        {"timelineItemLayout": "inherit"},
        {"sectionItemLayouts": {"simple_list": "inline"}},
        {"sectionItemLayouts": {"experience-1": "inline"}},
        {"sectionItemLayouts": {"unknown": "split"}},
        {"sectionItemLayouts": {"education": "inherit"}},
        {"sectionItemLayouts": {"project": "list"}},
        {"sectionItemLayouts": {"publication": None}},
        {"sectionItemLayouts": None},
        {"sectionItemLayouts": []},
    ],
)
def test_invalid_section_layouts_cannot_create_update_or_import_templates(
    client: TestClient, invalid_layout: dict
) -> None:
    template = _template()
    created = _create(client, template)
    invalid = deepcopy(template)
    invalid["layout"].update(invalid_layout)

    rejected_create = client.post("/api/templates", json={"template": invalid})
    assert rejected_create.status_code == 422
    rejected_update = client.put(
        f"/api/templates/{created['id']}", json={"template": invalid}
    )
    assert rejected_update.status_code == 422
    assert _detail(client, created["id"])["template"] == created
    assert len(client.get("/api/templates").json()["data"]["templates"]) == 1

    rejected_import = client.post(
        "/api/import/templates",
        files={
            "file": (
                "invalid.json",
                json.dumps(
                    {
                        "format": "reseno.template",
                        "formatVersion": 1,
                        "templates": [invalid],
                    }
                ),
                "application/json",
            )
        },
    )
    assert rejected_import.status_code == 400
    assert rejected_import.json()["message"] == "TEMPLATE_ARTIFACT_INVALID"
