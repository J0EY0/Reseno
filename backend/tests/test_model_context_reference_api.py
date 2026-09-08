from pathlib import Path

import pytest

from app.services import model_metadata


@pytest.mark.parametrize("provider", ["ollama", "vllm", "sglang", "custom-cloud"])
def test_context_lookup_uses_bundle_without_credentials_or_config_changes(
    client, monkeypatch, provider,
) -> None:
    monkeypatch.setattr(
        model_metadata,
        "MODEL_METADATA_SNAPSHOT_PATH",
        Path(model_metadata.__file__).with_name("model_metadata_snapshot.json"),
    )
    model_metadata._CATALOG_CACHE = None

    async def reject_fetch():
        raise AssertionError("Context lookup must not download catalogs.")

    monkeypatch.setattr(model_metadata, "_fetch_catalog", reject_fetch)
    monkeypatch.setattr(model_metadata, "_fetch_reasoning_catalog", reject_fetch)
    before = client.get("/api/model-configs").json()["data"]
    response = client.post(
        "/api/model-providers/context-window",
        json={"provider": provider, "model": " Qwen/Qwen3-32B "},
    )

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] == "found"
    assert result["contextWindowTokens"] > 0
    assert result["matchedModel"] == "alibaba/qwen3-32b"
    assert result["source"] == "models.dev"
    assert client.get("/api/model-configs").json()["data"] == before


def test_unknown_context_lookup_returns_no_assumed_limit(client) -> None:
    response = client.post(
        "/api/model-providers/context-window",
        json={"provider": "ollama", "model": "unlisted-local-alias:latest"},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "status": "not_found",
        "contextWindowTokens": None,
        "matchedModel": None,
        "source": None,
    }


@pytest.mark.parametrize("provider", ["openai", "qwen", "missing-provider"])
def test_context_reference_endpoint_rejects_non_manual_providers(
    client, provider,
) -> None:
    response = client.post(
        "/api/model-providers/context-window",
        json={"provider": provider, "model": "Qwen/Qwen3-32B"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize("model", ["", "   "])
def test_context_reference_endpoint_rejects_blank_model(client, model) -> None:
    response = client.post(
        "/api/model-providers/context-window",
        json={"provider": "ollama", "model": model},
    )

    assert response.status_code == 422


def test_context_reference_endpoint_requires_authentication(
    unauthenticated_client,
) -> None:
    response = unauthenticated_client.post(
        "/api/model-providers/context-window",
        json={"provider": "ollama", "model": "Qwen/Qwen3-32B"},
    )

    assert response.status_code == 401
