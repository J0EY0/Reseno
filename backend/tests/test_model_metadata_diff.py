from copy import deepcopy

from scripts.model_metadata_diff import render_metadata_diff, semantic_snapshot


def _snapshot() -> dict:
    return {
        "version": 6,
        "source": "public-catalogs",
        "catalogs": {
            "litellm": {
                "fetchedAt": "2026-09-08T00:00:00+00:00",
                "providers": {
                    "openai": {
                        "gpt-test": {
                            "contextWindowTokens": 128000,
                            "supportsThinking": True,
                            "reasoningOptions": ["low", "high"],
                        },
                    },
                },
                "contextModels": {
                    "ollama/qwen": {
                        "aliases": ["qwen"],
                        "contextWindowTokens": 32768,
                    },
                },
            },
        },
    }


def test_semantic_snapshot_only_removes_catalog_fetch_timestamps() -> None:
    original = _snapshot()
    original["fetchedAt"] = "snapshot-level-fact"
    model = original["catalogs"]["litellm"]["providers"]["openai"]["gpt-test"]
    model["fetchedAt"] = "model-level-fact"
    saved = deepcopy(original)

    normalized = semantic_snapshot(original)

    assert original == saved
    assert "fetchedAt" not in normalized["catalogs"]["litellm"]
    assert normalized["fetchedAt"] == "snapshot-level-fact"
    assert normalized["version"] == 6
    assert normalized["source"] == "public-catalogs"
    normalized_model = normalized["catalogs"]["litellm"]["providers"]["openai"][
        "gpt-test"
    ]
    assert normalized_model["fetchedAt"] == "model-level-fact"
    normalized_model["reasoningOptions"].append("medium")
    assert original == saved


def test_timestamp_only_changes_have_no_semantic_report() -> None:
    before = _snapshot()
    after = deepcopy(before)
    after["catalogs"]["litellm"]["fetchedAt"] = "2026-09-19T00:00:00+00:00"

    assert semantic_snapshot(before) == semantic_snapshot(after)
    assert render_metadata_diff(before, after).endswith("No semantic changes.\n")
    assert "2026-09" not in render_metadata_diff(before, after)
    assert semantic_snapshot({}) == {}


def test_reports_added_removed_and_modified_models_and_fields() -> None:
    before = _snapshot()
    old_models = before["catalogs"]["litellm"]["providers"]["openai"]
    old_models["removed-model"] = {"maxOutputTokens": 1024}
    after = deepcopy(before)
    models = after["catalogs"]["litellm"]["providers"]["openai"]
    del models["removed-model"]
    models["new-model"] = {"contextWindowTokens": 1000000}
    model = models["gpt-test"]
    model["contextWindowTokens"] = 256000
    model["supportsTools"] = False
    del model["supportsThinking"]
    model["reasoningOptions"] = ["low", "medium", "high"]

    report = render_metadata_diff(before, after)

    assert "| Provider model records | 1 | 1 | 1 |" in report
    assert "| <code>litellm</code> | Provider models | 1 | 1 | 1 |" in report
    assert "Source <code>litellm</code> — Modified" in report
    assert "<code>openai</code> | <code>new-model</code> | Added" in report
    assert "<code>openai</code> | <code>removed-model</code> | Removed" in report
    assert (
        "<code>contextWindowTokens</code> | <code>128000</code> | <code>256000</code>"
        in report
    )
    assert "<code>supportsTools</code> | — | <code>false</code>" in report
    assert "<code>supportsThinking</code> | <code>true</code> | —" in report
    assert "&quot;medium&quot;" in report
    assert "<code>reasoningOptions</code>" in report
    assert "1000000" in report and "1024" in report
    assert report.index("<code>gpt-test</code>") < report.index(
        "<code>new-model</code>"
    )


def test_reports_context_models_without_assuming_provider_nesting() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["contextModels"]["old/context"] = {"aliases": []}
    after = deepcopy(before)
    contexts = after["catalogs"]["litellm"]["contextModels"]
    contexts.pop("old/context")
    contexts["new/context"] = {"aliases": ["new"], "contextWindowTokens": 64000}
    contexts["ollama/qwen"]["aliases"] = ["qwen", "qwen:latest"]
    contexts["ollama/qwen"]["contextWindowTokens"] = 65536

    report = render_metadata_diff(before, after)

    assert "| Context model records | 1 | 1 | 1 |" in report
    assert "| <code>litellm</code> | Context models | 1 | 1 | 1 |" in report
    assert "#### Context models" in report
    assert "<code>new/context</code> | Added" in report
    assert "<code>old/context</code> | Removed" in report
    assert "<code>ollama/qwen</code> | Modified" in report
    assert "qwen:latest" in report
    assert "<code>32768</code> | <code>65536</code>" in report


def test_reports_snapshot_source_version_and_catalog_metadata_changes() -> None:
    before = _snapshot()
    before["catalogs"]["litellm"]["source"] = "old-upstream"
    after = deepcopy(before)
    after["version"] = 7
    after["source"] = "updated-public-catalogs"
    after["catalogs"]["litellm"]["source"] = "new-upstream"

    report = render_metadata_diff(before, after)

    assert "| Snapshot fields | 0 | 0 | 2 |" in report
    assert "<code>version</code> | Modified | <code>6</code> | <code>7</code>" in report
    assert "updated-public-catalogs" in report
    assert "#### Catalog metadata" in report
    assert "old-upstream" in report and "new-upstream" in report


def test_reports_added_removed_sources_and_empty_providers() -> None:
    before = _snapshot()
    after = _snapshot()
    after["catalogs"] = {
        "modelsDev": {
            "fetchedAt": "today",
            "providers": {
                "empty-provider": {},
                "openai": {"new-model": {"supportsTools": True}},
            },
            "contextModels": {},
        },
    }

    report = render_metadata_diff(before, after)

    assert "| Sources | 1 | 1 | 0 |" in report
    assert "| Provider records | 2 | 1 | 0 |" in report
    assert "Source <code>litellm</code> — Removed" in report
    assert "Source <code>modelsDev</code> — Added" in report
    assert "Provider <code>empty-provider</code>: added." in report
    assert "<code>gpt-test</code> | Removed" in report
    assert "<code>new-model</code> | Added" in report


def test_first_snapshot_reports_all_entities() -> None:
    report = render_metadata_diff({}, _snapshot())

    assert "| Sources | 1 | 0 | 0 |" in report
    assert "| Provider records | 1 | 0 | 0 |" in report
    assert "| Provider model records | 1 | 0 | 0 |" in report
    assert "| Context model records | 1 | 0 | 0 |" in report
    assert "| Snapshot fields | 2 | 0 | 0 |" in report


def test_nested_fields_and_null_values_are_reported_without_omissions() -> None:
    before = _snapshot()
    old = before["catalogs"]["litellm"]["providers"]["openai"]["gpt-test"]
    old["limits"] = {"context/size": 100, "removed": None}
    after = deepcopy(before)
    new = after["catalogs"]["litellm"]["providers"]["openai"]["gpt-test"]
    new["limits"] = {"context/size": 200, "added": None}

    report = render_metadata_diff(before, after)

    assert (
        "<code>limits/context&#126;1size</code> | <code>100</code> | <code>200</code>"
        in report
    )
    assert "<code>limits/removed</code> | <code>null</code> | —" in report
    assert "<code>limits/added</code> | — | <code>null</code>" in report


def test_report_is_stable_regardless_of_object_key_order() -> None:
    before = _snapshot()
    after = deepcopy(before)
    after["source"] = "another-source"
    after["catalogs"]["litellm"]["providers"]["zzz"] = {"z": {}, "a": {}}
    after["catalogs"]["litellm"]["providers"]["aaa"] = {"z": {}, "a": {}}

    def reverse_keys(value: object) -> object:
        if isinstance(value, dict):
            return {key: reverse_keys(item) for key, item in reversed(value.items())}
        if isinstance(value, list):
            return [reverse_keys(item) for item in value]
        return value

    assert render_metadata_diff(before, after) == render_metadata_diff(
        reverse_keys(before),
        reverse_keys(after),
    )


def test_upstream_text_cannot_inject_markdown_html_or_mentions() -> None:
    injected = "<script>alert(1)</script>|`[link](javascript:evil)\n# @everyone *_~ &"
    snapshot = {
        "version": 6,
        "catalogs": {
            injected: {
                "providers": {injected: {injected: {"label": injected}}},
                "contextModels": {},
            },
        },
    }

    report = render_metadata_diff({}, snapshot)

    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "[link]" not in report
    assert "&#91;link&#93;" in report
    assert "@everyone" not in report
    assert "&#64;everyone" in report
    assert "&#124;" in report
    assert "&#96;" in report
    assert "\n# @" not in report
    assert "&#92;n#" in report
    for row in report.splitlines():
        if row.startswith("| <code>"):
            assert row.count("|") in {5, 6, 7}


def test_large_changes_are_not_silently_truncated() -> None:
    snapshot = _snapshot()
    models = snapshot["catalogs"]["litellm"]["providers"]["openai"]
    models.update(
        {f"probe-{index:04d}": {"contextWindowTokens": index} for index in range(400)}
    )

    report = render_metadata_diff({}, snapshot)

    assert "| Provider model records | 401 | 0 | 0 |" in report
    for model in models:
        assert f"<code>{model}</code>" in report


def test_each_source_has_separate_counts_and_collapsed_details() -> None:
    before = _snapshot()
    before["catalogs"]["modelsDev"] = deepcopy(before["catalogs"]["litellm"])
    after = deepcopy(before)
    after["catalogs"]["litellm"]["providers"]["openai"]["gpt-test"]["supportsTools"] = (
        True
    )
    after["catalogs"]["modelsDev"]["providers"]["openai"]["new-model"] = {}
    del after["catalogs"]["modelsDev"]["contextModels"]["ollama/qwen"]

    report = render_metadata_diff(before, after)

    assert "Counts represent source records" in report
    assert "`—` means absent; `false` is a recorded value." in report
    assert "| <code>litellm</code> | Provider models | 0 | 0 | 1 |" in report
    assert "| <code>modelsDev</code> | Provider models | 1 | 0 | 0 |" in report
    assert "| <code>modelsDev</code> | Context models | 0 | 1 | 0 |" in report
    assert report.count("<details>\n<summary>Source ") == 2
    assert report.count("</summary>\n\n#### ") == 2
    assert report.count("\n\n</details>") == 2
