import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from scripts import model_metadata_report
from scripts.model_metadata_report import render_report


def _snapshot() -> dict[str, Any]:
    return {
        "version": 6,
        "source": "litellm:model_prices_and_context_window+models.dev",
        "catalogs": {
            source: {
                "fetchedAt": "2026-09-08T00:00:00+00:00",
                "providers": {},
                "contextModels": {},
            }
            for source in ("litellm", "modelsDev")
        },
    }


def test_report_counts_provider_pairs_and_context_records_per_source() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["providers"] = {
        "openai": {
            "shared": {"maxOutputTokens": 100, "supportsTools": False},
            "removed": {"supportsImage": True},
        },
        "anthropic": {"shared": {"maxOutputTokens": 100}},
    }
    before["catalogs"]["modelsDev"]["contextModels"] = {
        "base/shared": {"contextWindowTokens": 100},
        "base/removed": {"contextWindowTokens": 200},
    }
    after = copy.deepcopy(before)
    models = after["catalogs"]["litellm"]["providers"]["openai"]
    del models["removed"]
    models["added"] = {"supportsImage": False}
    models["shared"] = {"maxOutputTokens": 200, "supportsTools": True}
    after["catalogs"]["modelsDev"]["providers"] = {
        "openai": {"shared": {"canDisableThinking": False}},
    }
    after["catalogs"]["modelsDev"]["contextModels"] = {
        "base/shared": {"contextWindowTokens": 300, "aliases": ["Shared/alias"]},
        "base/added": {"contextWindowTokens": 400},
    }

    report = render_report(before, after)
    litellm, models_dev = report.split("### models.dev")
    assert "| Provider models | 1 | 1 | 1 |" in litellm
    assert "| Context references | 0 | 0 | 0 |" in litellm
    assert "| Provider models | 1 | 0 | 0 |" in models_dev
    assert "| Context references | 1 | 1 | 1 |" in models_dev
    assert "openai / added" in litellm
    assert "openai / removed" in litellm
    assert "anthropic / shared" not in report
    assert (
        "<code>maxOutputTokens</code> | <code>100</code> | <code>200</code>" in report
    )
    assert "base/added" in models_dev
    assert "base/removed" in models_dev
    assert (
        "<code>contextWindowTokens</code> | <code>100</code> | <code>300</code>"
        in report
    )
    assert "<code>aliases</code> | — |" in models_dev


def test_timestamps_only_are_displayed_without_model_changes() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["providers"] = {
        "openai": {"shared": {"supportsTools": False}},
    }
    after = copy.deepcopy(before)
    for catalog in after["catalogs"].values():
        catalog["fetchedAt"] = "2026-09-14T12:34:56+00:00"

    report = render_report(before, after)
    assert report.count("| Provider models | 0 | 0 | 0 |") == 2
    assert report.count("| Context references | 0 | 0 | 0 |") == 2
    assert report.count("No model records changed.") == 2
    assert "2026-09-08T00:00:00&#43;00:00" in report
    assert "2026-09-14T12:34:56&#43;00:00" in report
    assert "| Change |" not in report
    assert "Snapshot field" not in report


def test_field_additions_removals_and_false_values_are_distinct() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["providers"] = {
        "openai": {
            "test": {
                "supportsImage": False,
                "supportsTools": True,
            },
        },
    }
    after = copy.deepcopy(before)
    after["catalogs"]["litellm"]["providers"]["openai"]["test"] = {
        "supportsTools": False,
        "canDisableThinking": False,
    }

    report = render_report(before, after)
    assert "| Provider models | 0 | 0 | 1 |" in report
    assert "<code>supportsImage</code> | <code>false</code> | — |" in report
    assert (
        "<code>supportsTools</code> | <code>true</code> | <code>false</code> |"
        in report
    )
    assert "<code>canDisableThinking</code> | — | <code>false</code> |" in report


def test_snapshot_fields_are_reported_and_json_types_are_compared() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["providers"] = {
        "openai": {"test": {"flag": False}},
    }
    after = copy.deepcopy(before)
    after["version"] = 7
    after["source"] = "changed"
    after["catalogs"]["litellm"]["providers"]["openai"]["test"]["flag"] = 0

    report = render_report(before, after)
    assert "| version | <code>6</code> | <code>7</code> |" in report
    assert "| source |" in report
    assert '<code>"changed"</code>' in report
    assert "<code>flag</code> | <code>false</code> | <code>0</code> |" in report


def test_report_is_stable_across_key_order_and_leaves_inputs_unchanged() -> None:
    before = _snapshot()
    after = copy.deepcopy(before)
    after["catalogs"]["litellm"]["providers"] = {
        "openai": {
            "z-last": {"supportsTools": False, "maxOutputTokens": 200},
            "a-first": {"supportsTools": True, "maxOutputTokens": 100},
        },
    }
    original_before, original_after = copy.deepcopy(before), copy.deepcopy(after)

    def reverse_keys(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: reverse_keys(item) for key, item in reversed(value.items())}
        return value

    report = render_report(before, after)
    assert report == render_report(reverse_keys(before), reverse_keys(after))
    assert report.index("openai / a-first") < report.index("openai / z-last")
    assert before == original_before
    assert after == original_after


def test_untrusted_text_cannot_add_markdown_rows_html_or_mentions() -> None:
    before = _snapshot()
    model = "@team|[link](url)\n#title"
    before["catalogs"]["modelsDev"]["providers"] = {
        "openai": {model: {"<field>|@user": "old"}},
    }
    after = copy.deepcopy(before)
    after["source"] = "<script>@org/team</script>"
    after["catalogs"]["modelsDev"]["providers"]["openai"][model] = {
        "<field>|@user": "</code> **bold** `code` @all |\r\n",
    }

    report = render_report(before, after)
    assert "@" not in report
    assert "<script>" not in report
    assert "<field>" not in report
    assert "[link]" not in report
    assert "**bold**" not in report
    assert "&#64;team&#124;&#91;link&#93;" in report
    assert "&#60;field&#62;&#124;&#64;user" in report
    assert "\\u000a&#35;title" in report
    detail_rows = [
        line for line in report.splitlines() if line.startswith("| Modified |")
    ]
    assert len(detail_rows) == 1
    assert detail_rows[0].count("|") == 6


def test_report_limits_detail_rows_and_bytes_but_keeps_exact_counts() -> None:
    before, after = _snapshot(), _snapshot()
    after["catalogs"]["litellm"]["providers"] = {
        "openai": {
            f"model-{index:04d}": {"sourceKey": "界" * 1_000, "supportsTools": False}
            for index in range(1_000)
        },
    }
    after["catalogs"]["modelsDev"]["contextModels"] = {
        f"base/{index}": {"contextWindowTokens": 100} for index in range(3)
    }

    report = render_report(before, after)
    assert "| Provider models | 1000 | 0 | 0 |" in report
    assert "| Context references | 3 | 0 | 0 |" in report
    assert sum(line.startswith("| Added |") for line in report.splitlines()) == 50
    assert "950 additional detail rows omitted" in report
    assert "3 additional detail rows omitted" in report
    assert "…" in report
    assert len(report.encode("utf-8")) < 50_000


def test_modified_and_removed_records_precede_additions_across_sources() -> None:
    before, after = _snapshot(), _snapshot()
    after["catalogs"]["litellm"]["providers"] = {
        "openai": {
            f"new-{index:03d}": {"supportsTools": False} for index in range(100)
        },
    }
    before["catalogs"]["modelsDev"]["providers"] = {
        "openai": {"changed": {"canDisableThinking": True}},
    }
    after["catalogs"]["modelsDev"]["providers"] = {
        "openai": {"changed": {"canDisableThinking": False}},
    }
    before["catalogs"]["modelsDev"]["contextModels"] = {
        "removed-reference": {"contextWindowTokens": 100},
    }

    report = render_report(before, after)
    assert sum(line.startswith("| Added |") for line in report.splitlines()) == 48
    assert "| Modified | <code>openai / changed</code>" in report
    assert "| Removed | <code>removed-reference</code>" in report
    assert "52 additional detail rows omitted" in report


def test_cli_reads_isolated_files_without_modifying_inputs(tmp_path: Path) -> None:
    before, after = _snapshot(), _snapshot()
    after["catalogs"]["litellm"]["providers"] = {
        "openai": {"new": {"supportsImage": False}},
    }
    base_path, updated_path = tmp_path / "base.json", tmp_path / "updated.json"
    output_path = tmp_path / "report.md"
    base_path.write_text(json.dumps(before), encoding="utf-8")
    updated_path.write_text(json.dumps(after), encoding="utf-8")
    original = {path: path.read_bytes() for path in (base_path, updated_path)}

    subprocess.run(
        [
            sys.executable,
            str(Path(model_metadata_report.__file__).resolve()),
            "--base", str(base_path),
            "--updated", str(updated_path),
            "--output", str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert output_path.read_text(encoding="utf-8") == render_report(before, after)
    assert all(path.read_bytes() == content for path, content in original.items())
    assert set(tmp_path.iterdir()) == {base_path, updated_path, output_path}
