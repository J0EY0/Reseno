from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services import model_providers


@pytest.mark.parametrize("provider_id", ["anthropic", "google"])
def test_model_discovery_reads_every_page(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    requests: list[str] = []
    provider = model_providers.get_model_provider(provider_id)
    assert provider is not None and provider.api_family is not None

    def get_json(url: str, *, headers: dict[str, str]) -> dict[str, Any]:
        requests.append(url)
        query = parse_qs(urlsplit(url).query)
        if provider_id == "anthropic":
            page = int(query.get("after_id", ["0"])[0]) + 1
            return {
                "data": [{"id": f"claude-test-{page}"}],
                "has_more": page < 3,
                "last_id": str(page),
            }
        page = int(query.get("pageToken", ["0"])[0]) + 1
        return {
            "models": [{"name": f"models/gemini-test-{page}"}],
            **({"nextPageToken": str(page)} if page < 3 else {}),
        }

    monkeypatch.setattr(model_providers, "_get_json", get_json)
    monkeypatch.setattr(
        model_providers,
        "ensure_provider_model_metadata",
        lambda *_: True,
    )
    monkeypatch.setattr(model_providers, "resolve_models_metadata", lambda *_: {})
    models = model_providers.discover_provider_models(
        provider_id=provider_id,
        api_family=provider.api_family,
        api_url=provider.default_base_url,
        api_key="test-key",
    )

    assert len(requests) == 3
    prefix = "claude" if provider_id == "anthropic" else "gemini"
    assert [model.id for model in models] == [
        f"{prefix}-test-{page}" for page in (1, 2, 3)
    ]


@pytest.mark.parametrize("provider_id", ["anthropic", "google"])
def test_model_discovery_rejects_repeated_page_cursor(
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
) -> None:
    provider = model_providers.get_model_provider(provider_id)
    assert provider is not None and provider.api_family is not None
    payload = (
        {"data": [{"id": "claude-test"}], "has_more": True, "last_id": "same"}
        if provider_id == "anthropic"
        else {"models": [{"name": "gemini-test"}], "nextPageToken": "same"}
    )
    monkeypatch.setattr(model_providers, "_get_json", lambda *args, **kwargs: payload)

    with pytest.raises(model_providers.ModelDiscoveryError):
        model_providers.discover_provider_models(
            provider_id=provider_id,
            api_family=provider.api_family,
            api_url=provider.default_base_url,
            api_key="test-key",
        )
