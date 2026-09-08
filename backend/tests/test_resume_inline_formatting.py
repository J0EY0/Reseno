import json
from copy import deepcopy
from html import escape

import pytest
from fastapi.testclient import TestClient

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.contracts import OPERATION_SCHEMA
from app.services.agent.draft import DraftEditEngine
from app.services.agent.privacy import (
    AgentPrivacyPlaceholderError,
    restore_agent_edit_value,
    resume_hidden_terms,
    sanitize_agent_resume,
    sanitize_agent_text,
)
from app.services.agent.runtime.messages import AgentPromptCompiler
from app.services.llm import AgentLlmConfig
from app.services.resume_rich_text import resume_text_content


def _resume() -> dict:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "Ada Chen",
            "headline": "Research engineer",
            "location": "Taipei",
            "phone": "",
            "email": "ada@example.com",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            {
                "id": "publications",
                "kind": "publication",
                "title": "Publications",
                "items": [{
                    "id": "paper-1",
                    "title": "H2O research",
                    "authors": "Ada Chen1*, Ben Lee2†",
                    "venue": "Science & Engineering",
                    "date": "2026-09",
                    "url": "https://example.com/paper",
                    "description": "Shared first authors: *; corresponding author: †",
                }],
            },
        ],
    }


def _timed_resume(kind: str) -> dict:
    resume = _resume()
    if kind == "publication":
        return resume
    items = {
        "education": {
            "school": "Research University", "degree": "MSc", "major": "Computing",
            "gpa": "", "location": "Taipei", "period": "2025 - 2026",
            "description": "", "highlights": [],
        },
        "experience": {
            "company": "Research Lab", "position": "Engineer", "location": "Taipei",
            "period": "2025 - 2026", "description": "", "highlights": [],
        },
        "project": {
            "name": "Research tools", "role": "Engineer", "period": "2025 - 2026",
            "url": "", "techStack": ["React", "D3.js", "C++"],
            "description": "", "highlights": [],
        },
        "achievement": {
            "name": "Research award", "issuer": "Research Society",
            "date": "2026-09", "url": "", "description": "",
        },
    }
    resume["sections"] = [{
        "id": kind, "kind": kind, "title": kind.title(),
        "items": [{"id": "item-1", **items[kind]}],
    }]
    return resume


def _engine(resume: dict) -> DraftEditEngine:
    return DraftEditEngine.open(AgentChatRequest(
        message=AgentConversationItem(
            id="format-authors",
            role="user",
            text="Format the author markers; preserve every name and symbol.",
        ),
        locale="en",
        resume=deepcopy(resume),
    ))


def _author_edit(value: str) -> list[dict]:
    return [{
        "operation": {
            "type": "update_item",
            "sectionId": "publications",
            "itemId": "paper-1",
            "patch": {"authors": value},
        },
    }]


@pytest.mark.parametrize("mark", ["strong", "em", "u", "sup", "sub"])
@pytest.mark.parametrize("remove", [False, True])
def test_agent_inline_format_changes_preserve_review_snapshots(
    mark: str,
    remove: bool,
) -> None:
    plain = "Ada Chen1*, Ben Lee2†"
    formatted = f"<p>Ada Chen<{mark}>1*</{mark}>, Ben Lee<{mark}>2†</{mark}></p>"
    before, after = (formatted, plain) if remove else (plain, formatted)
    resume = _resume()
    resume["sections"][0]["items"][0]["authors"] = before
    engine = _engine(resume)

    batch = engine.execute(_author_edit(after))

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["authors"] == after
    assert resume["sections"][0]["items"][0]["authors"] == before
    assert len(batch.edits) == 1
    assert len(batch.edits[0].diffs) == 1
    diff = batch.edits[0].diffs[0]
    assert diff["before"] == before
    assert diff["after"] == after
    assert diff["path"] == "sections.publications.items.paper-1.authors"

    repeated = engine.execute(_author_edit(after))

    assert repeated.accepted is False
    assert repeated.edits == batch.edits
    assert repeated.revision == batch.revision
    assert repeated.draft_resume == batch.draft_resume


@pytest.mark.parametrize("field", ["title", "venue"])
@pytest.mark.parametrize("remove", [False, True])
def test_agent_academic_italic_changes_preserve_independent_emphasis(
    field: str,
    remove: bool,
) -> None:
    resume = _resume()
    item = resume["sections"][0]["items"][0]
    text = item[field]
    ordinary = f"<p><em>{escape(text)}</em></p>"
    academic = (
        '<p><span data-academic-italic="true">'
        f"<em>{escape(text)}</em></span></p>"
    )
    before, after = (academic, ordinary) if remove else (ordinary, academic)
    item[field] = before
    engine = _engine(resume)
    edits = [{
        "operation": {
            "type": "update_item",
            "sectionId": "publications",
            "itemId": "paper-1",
            "patch": {field: after},
        },
    }]

    batch = engine.execute(edits)

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0][field] == after
    assert resume_text_content(after) == text
    assert item[field] == before
    assert len(batch.edits) == 1
    assert len(batch.edits[0].diffs) == 1
    diff = batch.edits[0].diffs[0]
    assert diff["path"] == f"sections.publications.items.paper-1.{field}"
    assert diff["before"] == before
    assert diff["after"] == after
    repeated = engine.execute(edits)
    assert repeated.accepted is False
    assert repeated.draft_resume == batch.draft_resume
    assert repeated.revision == batch.revision


@pytest.mark.parametrize(
    "kind", ["education", "experience", "project", "publication", "achievement"],
)
@pytest.mark.parametrize("remove", [False, True])
def test_agent_time_formatting_preserves_dates_and_rejects_new_dates(
    kind: str,
    remove: bool,
) -> None:
    resume = _timed_resume(kind)
    section = resume["sections"][0]
    item = section["items"][0]
    field = "period" if "period" in item else "date"
    plain = item[field]
    formatted = (
        '<p><u>2025</u> - <span data-academic-italic="true">2026</span></p>'
        if field == "period" else '<p><strong>20</strong>26-<em>09</em></p>'
    )
    before, after = (formatted, plain) if remove else (plain, formatted)
    item[field] = before
    engine = _engine(resume)
    operation = {
        "type": "update_item", "sectionId": section["id"], "itemId": item["id"],
        "patch": {field: after},
    }

    batch = engine.execute([{"operation": operation}])

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0][field] == after
    assert resume_text_content(after) == plain
    assert len(batch.edits[0].diffs) == 1
    assert batch.edits[0].diffs[0]["before"] == before
    assert batch.edits[0].diffs[0]["after"] == after
    assert engine.execute([{"operation": operation}]).accepted is False

    operation["patch"] = {field: "<p><strong>2030</strong></p>"}
    rejected = engine.execute([{"operation": operation}])
    assert rejected.accepted is False
    assert rejected.draft_resume == batch.draft_resume
    issue = next(issue for issue in rejected.issues
                 if issue["code"] == "unsupported_edit_claim")
    assert issue["claims"] == ["2030", f"identity:{field}:2030"]


@pytest.mark.parametrize("remove", [False, True])
def test_agent_tech_stack_formatting_uses_visible_technology_claims(
    remove: bool,
) -> None:
    resume = _timed_resume("project")
    item = resume["sections"][0]["items"][0]
    plain = item["techStack"]
    formatted = [
        "<p><strong>Re</strong>act</p>",
        "<p>D<sub>3</sub>.js</p>",
        '<p><span data-academic-italic="true">C&#43;&#43;</span></p>',
    ]
    before, after = (formatted, plain) if remove else (plain, formatted)
    item["techStack"] = before
    engine = _engine(resume)
    operation = {
        "type": "update_item", "sectionId": "project", "itemId": "item-1",
        "patch": {"techStack": after},
    }

    batch = engine.execute([{"operation": operation}])

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["techStack"] == after
    assert len(batch.edits[0].diffs) == 1
    assert batch.edits[0].diffs[0]["before"] == before
    assert batch.edits[0].diffs[0]["after"] == after
    assert engine.execute([{"operation": operation}]).accepted is False

    operation["patch"] = {"techStack": [*after, "<p><em>Kafka</em></p>"]}
    rejected = engine.execute([{"operation": operation}])
    assert rejected.accepted is False
    assert rejected.draft_resume == batch.draft_resume
    issue = next(issue for issue in rejected.issues
                 if issue["code"] == "unsupported_edit_claim")
    assert issue["claims"] == ["Kafka"]


def test_agent_can_move_formatted_grounded_technology_to_tech_stack() -> None:
    resume = _timed_resume("project")
    item = resume["sections"][0]["items"][0]
    item["description"] = "<p>Built with <strong>Ka</strong>fka.</p>"
    kafka = '<p><span data-academic-italic="true">Ka</span>fka</p>'
    batch = _engine(resume).execute([{
        "operation": {
            "type": "update_item", "sectionId": "project", "itemId": "item-1",
            "patch": {"techStack": [*item["techStack"], kafka]},
        },
    }])
    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["techStack"][-1] == kafka


def test_agent_keeps_existing_author_marks_when_another_field_changes() -> None:
    resume = _resume()
    authors = "<p><strong>Ada Chen</strong><sup>1*</sup>, Ben Lee<sup>2†</sup></p>"
    resume["sections"][0]["items"][0]["authors"] = authors
    engine = _engine(resume)

    batch = engine.execute([{
        "operation": {
            "type": "update_item",
            "sectionId": "publications",
            "itemId": "paper-1",
            "patch": {"title": "<p>H<sub>2</sub>O research</p>"},
        },
    }])

    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["authors"] == authors
    assert [diff["path"] for diff in batch.edits[0].diffs] == [
        "sections.publications.items.paper-1.title",
    ]


def test_agent_model_contract_exposes_inline_marks_for_insert_and_patch() -> None:
    branches = {
        branch["properties"]["type"]["const"]: branch
        for branch in OPERATION_SCHEMA["oneOf"]
    }
    patch = branches["update_item"]["properties"]["patch"]["properties"]
    publication = next(
        branch["properties"]
        for branch in branches["insert_item"]["properties"]["item"]["oneOf"]
        if "authors" in branch["properties"]
    )

    description = OPERATION_SCHEMA["description"]
    for mark in ("strong", "em", "u", "sup", "sub"):
        assert f"<{mark}>" in description
    assert "plain strings" in description
    assert "author order" in description
    assert '<span data-academic-italic="true">' in description
    assert json.dumps(OPERATION_SCHEMA).count("data-academic-italic") == 1
    project = next(
        branch["properties"]
        for branch in branches["insert_item"]["properties"]["item"]["oneOf"]
        if "techStack" in branch["properties"]
    )
    assert "URLs, email and phone stay plain" in description
    assert "techStack entries accept plain strings" in description
    for fields in (patch, project):
        assert fields["period"]["type"] == "string"
        assert fields["techStack"]["type"] == "array"
        assert fields["techStack"]["items"]["type"] == "string"
    for fields in (patch, publication):
        for field in ("title", "authors", "venue", "description", "date"):
            assert fields[field]["type"] == "string"


def test_inline_formatting_survives_save_read_versions_and_json_import(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "Research resume"},
    )
    assert created.status_code == 200
    item = created.json()["data"]["resume"]
    document = _resume()
    document["basic"].update({
        "name": "<p><strong>Ada Chen</strong></p>",
        "headline": "<p>Research <em>engineer</em></p>",
        "location": "<p><u>Taipei</u></p>",
        "summary": (
            '<p><span data-academic-italic="true">Research engineer</span></p>'
        ),
    })
    document["sections"][0]["items"][0].update({
        "title": (
            '<p><span data-academic-italic="true">'
            'H<sub>2</sub>O research</span></p>'
        ),
        "authors": (
            "<p><strong>Ada Chen</strong><sup>1*</sup>, Ben Lee<sup>2†</sup></p>"
        ),
        "venue": (
            '<p><em><span data-academic-italic="true">'
            'Science &amp; Engineering</span></em></p>'
        ),
        "date": "<p><strong>2026</strong>-09</p>",
        "description": "<p>Shared first authors: <sup>*</sup>; corresponding: †</p>",
    })
    document["sections"].append({
        "id": "projects",
        "kind": "project",
        "title": "Projects",
        "items": [{
            "id": "project-1",
            "name": "<p>H<sub>2</sub>O</p>",
            "role": "<p><strong>Researcher</strong></p>",
            "period": "<p><em>2025</em> - 2026</p>",
            "url": "https://example.com/project",
            "techStack": [
                "<p><strong>Python</strong></p>",
                '<p><span data-academic-italic="true">R</span></p>',
            ],
            "description": "<p>Measured 10<sup>3</sup> samples.</p>",
            "highlights": [
                '<ul><li>Studied <span data-academic-italic="true">'
                'H<sub>2</sub>O</span>.</li></ul>'
            ],
        }],
    })
    document["sections"].append({
        "id": "skills",
        "kind": "simple_list",
        "title": "Skills",
        "items": [{
            "id": "skill-1",
            "content": (
                '<ul><li><span data-academic-italic="true">'
                'H<sub>2</sub>O analysis</span>; 10<sup>3</sup> samples</li></ul>'
            ),
        }],
    })
    for kind in ("education", "experience", "achievement"):
        section = _timed_resume(kind)["sections"][0]
        timed_item = section["items"][0]
        timed_item["id"] = f"{kind}-1"
        field = "period" if "period" in timed_item else "date"
        timed_item[field] = f"<p><u>{timed_item[field]}</u></p>"
        document["sections"].append(section)
    payload = {
        key: item[key]
        for key in (
            "title", "documentLocale", "resume", "jobBrief", "typography",
            "template", "templateSettings",
        )
    }
    payload["resume"] = document
    saved = client.put(f"/api/resumes/{item['id']}", json=payload)
    assert saved.status_code == 200
    assert saved.json()["data"]["resume"]["resume"] == document
    repeated = client.put(f"/api/resumes/{item['id']}", json=payload)
    assert repeated.status_code == 200
    assert repeated.json()["data"]["versionId"] == saved.json()["data"]["versionId"]
    loaded = client.get(f"/api/resumes/{item['id']}")
    assert loaded.status_code == 200
    assert loaded.json()["data"]["resume"]["resume"] == document

    artifact = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [],
        "resumes": [payload],
    }
    imported = client.post(
        "/api/import/resume",
        files={"file": ("resume.json", json.dumps(artifact), "application/json")},
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["resumes"][0]["resume"] == document


@pytest.mark.parametrize("formatted", [False, True])
def test_inline_marks_preserve_identity_grounding_and_reject_new_claims(
    formatted: bool,
) -> None:
    document = _resume()
    document["sections"] = [{
        "id": "experience",
        "kind": "experience",
        "title": "Experience",
        "items": [{
            "id": "job-1",
            "company": "<p>Research <em>&amp;</em> Science</p>" if formatted
            else "Research & Science",
            "position": "<p>Research <strong>engineer</strong></p>" if formatted
            else "Research engineer",
            "location": "Taipei",
            "period": "2025 - 2026",
            "description": "Measured 30% improvement.",
            "highlights": [],
        }],
    }]
    engine = _engine(document)
    operation = {
        "type": "update_item",
        "sectionId": "experience",
        "itemId": "job-1",
        "patch": {
            "company": "Research & Science" if formatted
            else "<p><strong>Research</strong> &amp; Science</p>",
            "position": "Research engineer" if formatted
            else "<p>Research <u>engineer</u></p>",
            "description": "<p>Measured <strong>30%</strong> improvement.</p>",
        },
    }
    batch = engine.execute([{"operation": operation}])
    assert batch.accepted is True

    operation["patch"] = {
        "position": "<p>Research <strong>director</strong></p>",
        "description": "<p>Measured <strong>40%</strong> improvement.</p>",
    }
    rejected = engine.execute([{"operation": operation}])
    assert rejected.accepted is False
    assert rejected.draft_resume == batch.draft_resume
    issue = next(
        issue for issue in rejected.issues
        if issue["code"] == "unsupported_edit_claim"
    )
    assert issue["claims"] == ["40%", "identity:position:Research director"]


def test_formatted_identity_fields_keep_plain_mentions_private_and_restorable() -> None:
    document = _resume()
    document["basic"].update({
        "name": "<p><strong>Ada Chen</strong></p>",
        "location": "<p><u>Taipei</u></p>",
        "summary": "Ada Chen is based in Taipei.",
    })
    document["sections"][0]["items"][0]["authors"] = (
        "<p><strong>Ada Chen</strong><sup>1*</sup>, Ben Lee<sup>2†</sup></p>"
    )
    terms = resume_hidden_terms(document)
    assert terms == ("Ada Chen", "Taipei")

    visible = sanitize_agent_resume(document, hidden_terms=terms)
    assert "Ada Chen" not in json.dumps(visible)
    assert "Taipei" not in json.dumps(visible)
    assert visible["basic"]["summary"] == (
        "[redacted_identity_0] is based in [redacted_identity_1]."
    )
    authors = visible["sections"][0]["items"][0]["authors"]
    assert restore_agent_edit_value(authors, hidden_terms=terms) == (
        document["sections"][0]["items"][0]["authors"]
    )
    assert sanitize_agent_text("Ada_Chen_CV.pdf", hidden_terms=terms) == (
        "[redacted_identity_0]_CV.pdf"
    )


@pytest.mark.parametrize(
    ("name", "authors"),
    [
        ("Ada Chen", "<p><strong>Ada</strong> Chen<sup>†</sup></p>"),
        ("Ada Chen", "<p>A<em>da Ch</em>en<sup>†</sup></p>"),
        ("Ada Chen", "<p><strong>Ada <em>Chen</em></strong><sup>†</sup></p>"),
        ("王小明", "<p><strong>王</strong>小<em>明</em><sup>†</sup></p>"),
        ("Ada & Chen", "<p><strong>Ada &amp;</strong> Chen<sup>†</sup></p>"),
        (
            "Ada Chen",
            '<p><span data-academic-italic="true">Ada</span> Chen<sup>†</sup></p>',
        ),
        (
            "Ada & Chen",
            '<p><span data-academic-italic="true">'
            '<em>Ada &amp;</em></span> Chen<sup>†</sup></p>',
        ),
    ],
)
def test_split_mark_identity_redaction_preserves_exact_markup(
    name: str,
    authors: str,
) -> None:
    document = _resume()
    document["basic"]["name"] = name
    document["sections"][0]["items"][0]["authors"] = authors
    terms = resume_hidden_terms(document)

    sanitized = sanitize_agent_resume(document, hidden_terms=terms)
    visible_authors = sanitized["sections"][0]["items"][0]["authors"]

    assert resume_text_content(visible_authors).startswith("[redacted_identity_0_")
    assert all(character not in resume_text_content(visible_authors)
               for character in ("王", "小", "明"))
    assert restore_agent_edit_value(visible_authors, hidden_terms=terms) == authors
    assert sanitize_agent_text(visible_authors, hidden_terms=terms) == visible_authors


@pytest.mark.parametrize(
    ("value", "marker"),
    [
        ("<p>a<em>da</em>@example.com</p>", "[redacted_email]"),
        ("<p>ada&#64;<strong>example</strong>.com</p>", "[redacted_email]"),
        ("<p>+886 <strong>912</strong> 345 678</p>", "[redacted_phone]"),
        (
            '<p>a<span data-academic-italic="true">da</span>@example.com</p>',
            "[redacted_email]",
        ),
        (
            '<p>+886 <span data-academic-italic="true">912</span> 345 678</p>',
            "[redacted_phone]",
        ),
    ],
)
def test_contact_redaction_crosses_inline_marks(value: str, marker: str) -> None:
    sanitized = sanitize_agent_text(value)

    assert resume_text_content(sanitized) == marker
    with pytest.raises(AgentPrivacyPlaceholderError):
        restore_agent_edit_value(sanitized, hidden_terms=())


@pytest.mark.parametrize(
    "marker",
    [
        "[redacted_identity_0_3_1]",
        "[redacted_identity_0_0_100]",
        "[redacted_identity_0_-1_2]",
        "[redacted_identity_0_2_2]",
        "[redacted_identity_9_0_1]",
    ],
)
def test_identity_slice_markers_require_exact_valid_bounds(marker: str) -> None:
    with pytest.raises(AgentPrivacyPlaceholderError):
        restore_agent_edit_value(f"<p>{marker}</p>", hidden_terms=("Ada Chen",))


@pytest.mark.parametrize("authors", [
    "<p><strong>Ada</strong> Chen<sup>1*</sup>, Ben Lee</p>",
    '<p><span data-academic-italic="true">Ada</span> Chen<sup>1*</sup>, Ben Lee</p>',
])
def test_model_context_and_draft_keep_split_identity_formatting_private(
    authors: str,
) -> None:
    document = _resume()
    document["sections"][0]["items"][0]["authors"] = authors
    document["basic"]["summary"] = (
        '<p>Email: a<span data-academic-italic="true">da</span>@example.com</p>'
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="private-formatted-authors", role="user",
            text="Add † after Ben Lee; preserve the other author markers.",
        ),
        locale="en", resume=document,
    )
    config = AgentLlmConfig(
        client_id="inline-privacy-test", name="Test Model", provider="openai",
        model="test", base_url="https://example.test/v1", api_key="test",
        temperature=None, top_p=None, max_tokens=2048, timeout_seconds=60,
        context_window_tokens=128000,
    )
    prompt = AgentPromptCompiler(request, config).build()
    model_text = json.dumps(prompt.messages, ensure_ascii=False)
    assert "Ada" not in model_text
    assert "Chen" not in model_text
    assert "@example.com" not in model_text
    assert "redacted_identity_0_0_3" in model_text
    assert "redacted_email" in model_text

    visible = sanitize_agent_resume(document)
    replacement = visible["sections"][0]["items"][0]["authors"].replace(
        "Ben Lee", "Ben Lee†",
    )
    batch = DraftEditEngine.open(request).execute(_author_edit(replacement))
    assert batch.accepted is True
    assert batch.draft_resume["sections"][0]["items"][0]["authors"] == (
        authors.replace("Ben Lee", "Ben Lee†")
    )
    assert batch.draft_resume["basic"]["summary"] == document["basic"]["summary"]


def test_blank_resume_title_uses_visible_name_before_truncating(
    client: TestClient,
) -> None:
    document = _resume()
    name = "Ada & Chen " + "Researcher " * 6
    document["basic"]["name"] = f"<p><strong>{escape(name)}</strong></p>"
    created = client.post(
        "/api/resumes",
        json={"documentLocale": "en", "title": "", "resume": document},
    )
    assert created.status_code == 200
    item = created.json()["data"]["resume"]
    assert item["title"] == name.strip()[:50]
    payload = {
        key: item[key]
        for key in (
            "title", "documentLocale", "resume", "jobBrief", "typography",
            "template", "templateSettings",
        )
    }
    payload["title"] = " "
    saved = client.put(f"/api/resumes/{item['id']}", json=payload)
    assert saved.status_code == 200
    assert saved.json()["data"]["resume"]["title"] == name.strip()[:50]


def test_rich_redaction_preserves_attribute_and_comment_contact_scrubbing() -> None:
    value = (
        '<p><a href="mailto:ada@example.com">Email</a>'
        '<!-- Phone: +886 912 345 678 --></p>'
    )
    sanitized = sanitize_agent_text(value)
    assert sanitized == (
        '<p><a href="mailto:[redacted_email]">Email</a>'
        '<!-- Phone: [redacted_phone] --></p>'
    )


def test_rich_numeric_email_redaction_does_not_overlap_phone_match() -> None:
    sanitized = sanitize_agent_text('<p>12345<em>67890</em>@example.com</p>')
    assert sanitized == '<p>[redacted_email]<em></em></p>'


def test_split_identity_keeps_word_boundaries_outside_author_markers() -> None:
    value = '<p><strong>Ada</strong> Chenson</p>'
    assert sanitize_agent_text(value, hidden_terms=('Ada Chen',)) == value
    value = '<p><strong>Ada</strong> Chen1</p>'
    assert sanitize_agent_text(value, hidden_terms=('Ada Chen',)) == value
