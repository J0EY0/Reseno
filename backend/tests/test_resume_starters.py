from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
    validate_resume_document,
)
from app.services.template_presets import get_builtin_template_preset

EXPECTED_SECTIONS = {
    ("minimal", "zh"): [
        ("education", ""),
        ("experience", "实习经历"),
        ("project", "项目经历"),
        ("achievement", "荣誉奖项"),
        ("simple_list", "技能"),
    ],
    ("minimal", "en"): [
        ("education", ""),
        ("experience", "Internship Experience"),
        ("project", "Projects"),
        ("achievement", "Awards"),
        ("simple_list", "Skills"),
    ],
    ("modern", "zh"): [
        ("experience", "工作经历"),
        ("project", "代表项目"),
        ("achievement", "专业认证"),
        ("simple_list", "核心技能"),
        ("education", ""),
    ],
    ("modern", "en"): [
        ("experience", "Experience"),
        ("project", "Selected Project"),
        ("achievement", "Certification"),
        ("simple_list", "Core Skills"),
        ("education", ""),
    ],
    ("compact", "zh"): [
        ("experience", "工作经历"),
        ("project", "代表项目"),
        ("achievement", "专业认证"),
        ("simple_list", "核心技能"),
        ("education", ""),
    ],
    ("compact", "en"): [
        ("experience", "Experience"),
        ("project", "Selected Project"),
        ("achievement", "Certification"),
        ("simple_list", "Core Skills"),
        ("education", ""),
    ],
    ("classic", "zh"): [
        ("experience", "工作经历"),
        ("project", "代表项目"),
        ("achievement", "专业认证"),
        ("simple_list", "核心技能"),
        ("education", ""),
    ],
    ("classic", "en"): [
        ("experience", "Experience"),
        ("project", "Selected Project"),
        ("achievement", "Certification"),
        ("simple_list", "Core Skills"),
        ("education", ""),
    ],
    ("executive", "zh"): [
        ("experience", "高管经历"),
        ("project", "代表性转型项目"),
        ("achievement", "董事会与行业参与"),
        ("simple_list", "领导能力"),
        ("education", ""),
    ],
    ("executive", "en"): [
        ("experience", "Executive Experience"),
        ("project", "Selected Transformation"),
        ("achievement", "Board & Advisory"),
        ("simple_list", "Leadership Capabilities"),
        ("education", ""),
    ],
    ("academic", "zh"): [
        ("education", ""),
        ("experience", "研究经历"),
        ("publication", "代表性论文"),
        ("experience", "教学经历"),
        ("achievement", "荣誉与资助"),
        ("simple_list", "研究技能"),
    ],
    ("academic", "en"): [
        ("education", ""),
        ("experience", "Research Experience"),
        ("publication", "Selected Publications"),
        ("experience", "Teaching Experience"),
        ("achievement", "Honors & Grants"),
        ("simple_list", "Research Skills"),
    ],
}


def _explicit_resume() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "Imported Candidate",
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            {
                "id": "imported-skills",
                "kind": "simple_list",
                "title": "Imported Skills",
                "items": [
                    {
                        "id": "imported-skills-item",
                        "content": "<ul><li>Python</li></ul>",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(("template_id", "locale"), EXPECTED_SECTIONS)
def test_new_resume_uses_template_starter_structure(
    client: TestClient,
    template_id: str,
    locale: str,
) -> None:
    response = client.post(
        "/api/resumes",
        json={
            "documentLocale": locale,
            "template": template_id,
            "title": "Starter",
        },
    )

    assert response.status_code == 200
    document = response.json()["data"]["resume"]["resume"]
    assert validate_resume_document(document) == document
    assert document["basic"] == {
        "name": "",
        "headline": "",
        "phone": "",
        "email": "",
        "location": "",
        "avatar": "",
        "summary": "",
        "customFields": [],
    }
    assert [
        (section["kind"], section["title"]) for section in document["sections"]
    ] == EXPECTED_SECTIONS[(template_id, locale)]

    node_ids: list[str] = []
    for section in document["sections"]:
        node_ids.append(section["id"])
        assert len(section["items"]) == 1
        item = section["items"][0]
        node_ids.append(item["id"])
        assert all(
            item[field] == "" for field in ITEM_STRING_FIELDS_BY_KIND[section["kind"]]
        )
        assert all(
            item[field] == [] for field in ITEM_LIST_FIELDS_BY_KIND[section["kind"]]
        )

    assert all(node_ids)
    assert len(node_ids) == len(set(node_ids))


def test_custom_template_inherits_its_preset_starter(client: TestClient) -> None:
    academic = get_builtin_template_preset("academic")
    template_response = client.post(
        "/api/templates",
        json={
            "template": {
                "preset": "academic",
                "name": "Custom Academic",
                "description": "",
                "layout": deepcopy(academic["layout"]),
                "typography": deepcopy(academic["typography"]),
                "settings": deepcopy(academic["settings"]),
            }
        },
    )
    template_id = template_response.json()["data"]["template"]["id"]

    response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "zh",
            "template": template_id,
            "title": "Research",
        },
    )

    assert template_response.status_code == 200
    assert response.status_code == 200
    created = response.json()["data"]["resume"]
    assert created["template"] == template_id
    assert [
        (section["kind"], section["title"]) for section in created["resume"]["sections"]
    ] == EXPECTED_SECTIONS[("academic", "zh")]


def test_workspace_default_template_selects_its_starter(client: TestClient) -> None:
    default_response = client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": "executive"},
    )

    response = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Leadership"},
    )

    assert default_response.status_code == 200
    assert response.status_code == 200
    created = response.json()["data"]["resume"]
    assert created["template"] == "executive"
    assert [
        (section["kind"], section["title"]) for section in created["resume"]["sections"]
    ] == EXPECTED_SECTIONS[("executive", "en")]


def test_workspace_keeps_independent_defaults_for_each_document_locale(
    client: TestClient,
) -> None:
    zh_default = client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "zh", "templateId": "academic"},
    )
    en_default = client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": "executive"},
    )

    zh_resume = client.post(
        "/api/resumes",
        json={"documentLocale": "zh"},
    ).json()["data"]["resume"]
    en_resume = client.post(
        "/api/resumes",
        json={"documentLocale": "en"},
    ).json()["data"]["resume"]
    templates_page = client.get("/api/workspace/pages/templates")

    assert zh_default.json()["data"]["defaultTemplateIds"] == {
        "zh": "academic",
        "en": "minimal",
    }
    assert en_default.json()["data"]["defaultTemplateIds"] == {
        "zh": "academic",
        "en": "executive",
    }
    assert templates_page.json()["data"]["defaultTemplateIds"] == {
        "zh": "academic",
        "en": "executive",
    }
    assert (zh_resume["documentLocale"], zh_resume["template"]) == (
        "zh",
        "academic",
    )
    assert zh_resume["title"] == "未命名简历 1"
    assert (en_resume["documentLocale"], en_resume["template"]) == (
        "en",
        "executive",
    )
    assert en_resume["title"] == "Untitled Resume 2"


def test_template_trash_rebinds_resumes_to_their_language_default(
    client: TestClient,
) -> None:
    minimal = get_builtin_template_preset("minimal")
    custom_template = client.post(
        "/api/templates",
        json={
            "template": {
                "preset": "minimal",
                "name": "Shared Custom",
                "description": "",
                "layout": deepcopy(minimal["layout"]),
                "typography": deepcopy(minimal["typography"]),
                "settings": deepcopy(minimal["settings"]),
            }
        },
    ).json()["data"]["template"]
    client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "zh", "templateId": "academic"},
    )
    client.put(
        "/api/workspace/default-template",
        json={"documentLocale": "en", "templateId": "executive"},
    )

    resumes = {
        locale: client.post(
            "/api/resumes",
            json={
                "documentLocale": locale,
                "template": custom_template["id"],
                "title": locale,
            },
        ).json()["data"]["resume"]
        for locale in ("zh", "en")
    }

    trash_response = client.post(f"/api/templates/{custom_template['id']}/trash")
    rebound = {
        locale: client.get(f"/api/resumes/{resume['id']}").json()["data"]["resume"]
        for locale, resume in resumes.items()
    }

    assert trash_response.status_code == 200
    assert rebound["zh"]["template"] == "academic"
    assert rebound["en"]["template"] == "executive"
    assert rebound["zh"]["documentLocale"] == "zh"
    assert rebound["en"]["documentLocale"] == "en"


def test_explicit_resume_bypasses_template_starter(client: TestClient) -> None:
    document = _explicit_resume()

    response = client.post(
        "/api/resumes",
        json={
            "documentLocale": "zh",
            "resume": document,
            "template": "academic",
            "title": "Imported",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["resume"]["resume"] == document


def test_switching_template_does_not_rebuild_existing_sections(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={
            "documentLocale": "zh",
            "template": "minimal",
            "title": "Candidate",
        },
    ).json()["data"]["resume"]
    document = deepcopy(created["resume"])

    response = client.put(
        f"/api/resumes/{created['id']}",
        json={
            "title": created["title"],
            "documentLocale": created["documentLocale"],
            "resume": document,
            "jobBrief": created["jobBrief"],
            "typography": created["typography"],
            "template": "academic",
            "templateSettings": created["templateSettings"],
        },
    )

    assert response.status_code == 200
    switched = response.json()["data"]["resume"]
    assert switched["template"] == "academic"
    assert switched["resume"] == document
