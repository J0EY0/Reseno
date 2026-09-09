import os
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import templates
from tests.template_fixtures import portable_template


@pytest.mark.parametrize("phase", ["journal", "before_commit", "after_commit"])
@pytest.mark.parametrize("save_mode", ["autosave", "checkpoint", "discard"])
def test_template_publication_recovers_after_process_interruption(
    client: TestClient, phase: str, save_mode: str
) -> None:
    checkpoint = templates.create_template(portable_template("Explicit"))["template"]
    before = templates.update_template(
        checkpoint["id"], portable_template("Before"), save_mode="autosave"
    )["template"]
    program = """
import os
import sys
from pathlib import Path
from app.services import templates, template_publications
from tests.template_fixtures import portable_template
entity_id, phase, clock, save_mode = sys.argv[1:]
templates._utc_now = lambda: clock
if phase == 'journal':
    original = template_publications.os.replace
    def interrupt(source, destination):
        if Path(destination).parent.name == '.template-publications':
            os._exit(23)
        return original(source, destination)
    template_publications.os.replace = interrupt
elif phase == 'before_commit':
    original = templates._write_template_json
    def interrupt(entity_id, item):
        original(entity_id, item)
        os._exit(23)
    templates._write_template_json = interrupt
else:
    original = templates.connect
    class Connection:
        def __init__(self, conn): self.conn = conn
        def __getattr__(self, name): return getattr(self.conn, name)
        def __enter__(self): self.conn.__enter__(); return self
        def __exit__(self, *args): return self.conn.__exit__(*args)
        def execute(self, sql, *args):
            result = self.conn.execute(sql, *args)
            if sql.strip().upper() == 'COMMIT': os._exit(23)
            return result
    templates.connect = lambda: Connection(original())
if save_mode == 'discard':
    templates.discard_template_changes(entity_id)
else:
    templates.update_template(
        entity_id, portable_template('After'), save_mode=save_mode
    )
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            program,
            before["id"],
            phase,
            before["updatedAt"],
            save_mode,
        ],
        cwd=Path(__file__).parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 23, process.stderr
    committed_name = "Explicit" if save_mode == "discard" else "After"
    expected_name = committed_name if phase == "after_commit" else "Before"
    detail = templates.get_template_detail(before["id"])
    expected_checkpoint = (
        None if phase == "after_commit" and save_mode != "autosave" else checkpoint
    )
    assert detail["checkpoint"] == expected_checkpoint
    items = templates.list_templates()["templates"]
    assert items[0]["name"] == expected_name
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT name,saved_at FROM templates WHERE id=?", (before["id"],)
        ).fetchone()
    assert row["name"] == items[0]["name"]
    assert row["saved_at"] == items[0]["updatedAt"]
    from app.config import get_settings

    assert list((get_settings().storage_dir / ".template-publications").iterdir()) == []


@pytest.mark.parametrize("phase", ["before_commit", "after_commit"])
def test_interrupted_template_creation_is_resolved_before_catalog_reads(
    client: TestClient, phase: str
) -> None:
    from app.services.template_publications import recover_pending_template_publications

    template_id = "template-interrupted-create"
    program = """
import os
import sys
from app.services import templates
from tests.template_fixtures import portable_template
entity_id, phase = sys.argv[1:]
templates._generate_template_id = lambda: entity_id
if phase == 'before_commit':
    original = templates._write_template_json
    def interrupt(entity_id, item):
        original(entity_id, item)
        os._exit(23)
    templates._write_template_json = interrupt
else:
    original = templates.connect
    class Connection:
        def __init__(self, conn): self.conn = conn
        def __getattr__(self, name): return getattr(self.conn, name)
        def __enter__(self): self.conn.__enter__(); return self
        def __exit__(self, *args): return self.conn.__exit__(*args)
        def execute(self, sql, *args):
            result = self.conn.execute(sql, *args)
            if sql.strip().upper() == 'COMMIT': os._exit(23)
            return result
    templates.connect = lambda: Connection(original())
templates.create_template(portable_template('Created'))
"""
    result = subprocess.run(
        [sys.executable, "-c", program, template_id, phase],
        cwd=Path(__file__).parents[1],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 23, result.stderr
    recover_pending_template_publications()
    items = templates.list_templates()["templates"]
    if phase == "before_commit":
        assert items == []
        assert not templates._template_path(template_id).exists()
    else:
        assert len(items) == 1
        assert items[0]["name"] == "Created"
        assert items[0]["id"] == template_id


def test_old_publisher_finalization_preserves_a_later_commit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    before = templates.create_template(portable_template("Same name"))["template"]
    monkeypatch.setattr(templates, "_utc_now", lambda: before["updatedAt"])
    later = []

    class CommitThenCompete:
        def __init__(self, conn):
            self.conn = conn

        def __getattr__(self, name):
            return getattr(self.conn, name)

        def __enter__(self):
            self.conn.__enter__()
            return self

        def __exit__(self, *args):
            return self.conn.__exit__(*args)

        def execute(self, sql, *args):
            result = self.conn.execute(sql, *args)
            if sql.strip().upper() == "COMMIT":
                with monkeypatch.context() as competitor:
                    competitor.setattr(templates, "connect", connect)
                    payload = portable_template("Same name")
                    payload["settings"]["headingColor"] = "#123456"
                    later.append(
                        templates.update_template(before["id"], payload)["template"]
                    )
                raise RuntimeError("The earlier request lost its response")
            return result

    with monkeypatch.context() as interrupted:
        interrupted.setattr(templates, "connect", lambda: CommitThenCompete(connect()))
        with pytest.raises(RuntimeError, match="lost its response"):
            templates.update_template(before["id"], portable_template("Same name"))
    assert templates.list_templates()["templates"] == later
    assert later[0]["settings"]["headingColor"] == "#123456"
    assert datetime.fromisoformat(later[0]["updatedAt"]) > datetime.fromisoformat(
        before["updatedAt"]
    )


def test_interrupted_recovery_is_repeatable(
    client: TestClient,
) -> None:
    before = templates.create_template(portable_template("Before"))["template"]
    program = """
import os
import sys
from app.services import templates, template_publications
from tests.template_fixtures import portable_template
entity_id, phase = sys.argv[1:]
if phase == 'publish':
    original = templates._write_template_json
    def interrupt(entity_id, item):
        original(entity_id, item)
        os._exit(23)
    templates._write_template_json = interrupt
    templates.update_template(entity_id, portable_template('After'))
else:
    original = template_publications.restore_template_bytes
    def interrupt(path, content):
        original(path, content)
        os._exit(23)
    template_publications.restore_template_bytes = interrupt
    templates.list_templates()
"""
    for phase in ("publish", "recover"):
        result = subprocess.run(
            [sys.executable, "-c", program, before["id"], phase],
            cwd=Path(__file__).parents[1],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 23, result.stderr
    assert templates.list_templates()["templates"] == [before]
    assert templates.list_templates()["templates"] == [before]


def test_committed_template_response_survives_deferred_journal_cleanup(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sqlite3

    from app.services import template_publications

    def unavailable_cleanup_connection():
        raise sqlite3.OperationalError("Cleanup connection unavailable")

    with monkeypatch.context() as cleanup_failure:
        cleanup_failure.setattr(
            template_publications, "connect", unavailable_cleanup_connection
        )
        response = client.post(
            "/api/templates", json={"template": portable_template("Committed")}
        )
        assert response.status_code == 200
        template_id = response.json()["data"]["template"]["id"]
        updated = client.put(
            f"/api/templates/{template_id}",
            json={"template": portable_template("Updated")},
        )
        assert updated.status_code == 200
    assert templates.list_templates()["templates"] == [
        updated.json()["data"]["template"]
    ]
