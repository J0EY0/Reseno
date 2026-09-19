import json
from pathlib import Path
from typing import Any

import pytest

from app.services import model_metadata
from app.services.model_context_reference import valid_context_models


def _assert_snapshot_quality(path: Path) -> None:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(snapshot, dict)
    assert set(snapshot) == {"version", "source", "catalogs"}
    assert snapshot["version"] == model_metadata.MODEL_METADATA_CACHE_VERSION
    assert snapshot["source"] == model_metadata.MODEL_METADATA_CACHE_SOURCE
    assert isinstance(snapshot["catalogs"], dict)
    assert set(snapshot["catalogs"]) == {"litellm", "modelsDev"}

    for source, catalog in snapshot["catalogs"].items():
        assert isinstance(catalog, dict), source
        assert set(catalog) == {"fetchedAt", "providers", "contextModels"}, source
        assert model_metadata._parse_fetched_at(catalog["fetchedAt"]) is not None, (
            source
        )
        assert model_metadata._valid_providers(catalog["providers"]), source
        assert valid_context_models(catalog["contextModels"]), source
        if source == "modelsDev":
            assert catalog["contextModels"], source
        for provider, models in catalog["providers"].items():
            assert models, (source, provider)
            for model, record in models.items():
                assert model == model.strip(), (source, provider, model)
                assert model_metadata.is_provider_model(provider, model), (
                    source,
                    provider,
                    model,
                )
                source_key = record.get("sourceKey")
                assert isinstance(source_key, str) and source_key.strip(), (
                    source,
                    provider,
                    model,
                )
                if source == "modelsDev":
                    prefixes = tuple(
                        f"models.dev:{alias}/"
                        for alias in model_metadata.MODELS_DEV_PROVIDER_ALIASES[
                            provider
                        ]
                    )
                    assert source_key.startswith(prefixes), (provider, model)

    assert model_metadata._read_cache(path) == {"catalogs": snapshot["catalogs"]}


def _sample_snapshot() -> dict[str, Any]:
    return {
        "version": model_metadata.MODEL_METADATA_CACHE_VERSION,
        "source": model_metadata.MODEL_METADATA_CACHE_SOURCE,
        "catalogs": {
            source: {
                "fetchedAt": "2026-01-01T00:00:00+00:00",
                "providers": {
                    "openai": {
                        "gpt-test": {
                            "sourceKey": source_key,
                            "contextWindowTokens": 128000,
                            "supportsThinking": False,
                        },
                    },
                },
                "contextModels": {
                    "example/test-model": {
                        "contextWindowTokens": 32000,
                        "aliases": ["example/test-alias"],
                    },
                },
            }
            for source, source_key in (
                ("litellm", "gpt-test"),
                ("modelsDev", "models.dev:openai/gpt-test"),
            )
        },
    }


def test_bundled_snapshot_is_valid_and_loads_every_source() -> None:
    path = Path(model_metadata.__file__).with_name("model_metadata_snapshot.json")
    _assert_snapshot_quality(path)


def test_snapshot_quality_accepts_valid_model_facts(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(_sample_snapshot()), encoding="utf-8")
    _assert_snapshot_quality(path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (("version",), -1),
        (("source",), "unexpected-source"),
        (("catalogs",), {}),
        (("catalogs", "litellm", "fetchedAt"), "invalid-timestamp"),
        (("catalogs", "litellm", "providers"), {}),
        (("catalogs", "litellm", "providers", "openai"), {}),
        (
            (
                "catalogs",
                "litellm",
                "providers",
                "openai",
                "gpt-test",
                "contextWindowTokens",
            ),
            True,
        ),
        (
            (
                "catalogs",
                "litellm",
                "providers",
                "openai",
                "gpt-test",
                "supportsThinking",
            ),
            "false",
        ),
        (("catalogs", "litellm", "providers", "openai", "gpt-test", "unknownField"), 1),
        (("catalogs", "litellm", "providers", "openai", "gpt-test", "sourceKey"), ""),
        (
            ("catalogs", "modelsDev", "providers", "openai", "gpt-test", "sourceKey"),
            "wrong:openai/gpt-test",
        ),
        (("catalogs", "modelsDev", "contextModels"), {}),
        (
            (
                "catalogs",
                "modelsDev",
                "contextModels",
                "example/test-model",
                "contextWindowTokens",
            ),
            -1,
        ),
        (
            ("catalogs", "modelsDev", "contextModels", "example/test-model", "aliases"),
            ["duplicate", "duplicate"],
        ),
    ],
)
def test_snapshot_quality_rejects_corrupted_metadata(
    tmp_path: Path,
    field: tuple[str, ...],
    value: Any,
) -> None:
    snapshot = _sample_snapshot()
    parent = snapshot
    for key in field[:-1]:
        parent = parent[key]
    parent[field[-1]] = value
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot), encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_snapshot_quality(path)


def test_snapshot_quality_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text("not a JSON snapshot", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        _assert_snapshot_quality(path)
