from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services import model_configs
from app.services.llm_secrets import decrypt_api_key
from app.services.model_discovery_cache import write_cached_provider_models
from app.services.model_providers import DiscoveredModel


def _cache_cloud_model() -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="gpt-test",
                label="gpt-test",
                context_window_tokens=32_768,
                max_output_tokens=4_096,
                supports_image=False,
                thinking_control="none",
                metadata_source="test",
            ),
        ],
    )


@pytest.mark.parametrize(
    "scope_change",
    [
        {"provider": "anthropic"},
        {"apiFamily": "anthropic_messages"},
        {"apiUrl": "https://other.example/v1"},
    ],
    ids=["provider", "api-family", "base-url"],
)
def test_switching_credential_scope_without_api_key_does_not_reuse_old_secret(
    client: TestClient,
    scope_change: dict[str, str],
) -> None:
    initial_payload = {
        "provider": "openai",
        "providerKind": "custom",
        "apiFamily": "openai_compatible_chat",
        "nickname": "Trusted endpoint",
        "apiKey": "old-secret",
        "model": "gpt-test",
        "apiUrl": "https://trusted.example/v1",
        "temperature": 0.4,
        "topP": 0.9,
        "maxTokens": 1_000,
    }
    created = client.post("/api/model-configs", json=initial_payload)
    assert created.status_code == 200
    config_id = created.json()["data"]["id"]

    switched = client.post(
        "/api/model-configs",
        json={
            **initial_payload,
            "id": config_id,
            "apiKey": None,
            **scope_change,
        },
    )

    assert switched.status_code == 200
    assert switched.json()["data"]["apiKeyPreview"] == ""
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT encrypted_api_key FROM llm_configs WHERE client_id = ?",
            (config_id,),
        ).fetchone()

    assert row is not None
    assert row["encrypted_api_key"] is None


@pytest.mark.parametrize("provider_kind", ["custom", "cloud"])
def test_nickname_update_cannot_restore_a_concurrently_replaced_api_key(
    client: TestClient,
    monkeypatch,
    provider_kind: str,
) -> None:
    _cache_cloud_model()
    initial_payload = {
        "provider": "openai",
        "providerKind": provider_kind,
        "apiFamily": (
            "openai_responses" if provider_kind == "cloud" else "openai_compatible_chat"
        ),
        "nickname": "Original",
        "apiKey": "old-secret",
        "model": "gpt-test",
        "apiUrl": "https://api.openai.com/v1",
        "temperature": 0.4,
        "topP": 0.9,
        "maxTokens": 1_000,
    }
    created = client.post("/api/model-configs", json=initial_payload)
    config_id = created.json()["data"]["id"]
    both_requests_read_old_key = Barrier(2)
    key_update_committed = Event()
    original_build_values = model_configs._build_upsert_values

    def synchronize_after_read(item, existing):
        values = original_build_values(item, existing)
        both_requests_read_old_key.wait(timeout=5)
        if not item.api_key:
            assert key_update_committed.wait(timeout=5)
        return values

    monkeypatch.setattr(
        model_configs,
        "_build_upsert_values",
        synchronize_after_read,
    )
    second_client = TestClient(client.app, headers=dict(client.headers))

    def replace_key():
        try:
            return client.post(
                "/api/model-configs",
                json={
                    **initial_payload,
                    "id": config_id,
                    "apiKey": "new-secret",
                },
            )
        finally:
            key_update_committed.set()

    def rename_without_key():
        return second_client.post(
            "/api/model-configs",
            json={
                **initial_payload,
                "id": config_id,
                "nickname": "Renamed",
                "apiKey": None,
            },
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            key_future = executor.submit(replace_key)
            rename_future = executor.submit(rename_without_key)
            key_response = key_future.result()
            rename_response = rename_future.result()
    finally:
        second_client.close()

    assert key_response.status_code == 200
    assert rename_response.status_code == 200
    with closing(connect()) as conn:
        row = conn.execute(
            "SELECT name, encrypted_api_key FROM llm_configs WHERE client_id = ?",
            (config_id,),
        ).fetchone()

    assert row is not None
    assert row["name"] == "Renamed"
    assert decrypt_api_key(row["encrypted_api_key"]) == "new-secret"


@pytest.mark.parametrize("provider_kind", ["custom", "cloud"])
def test_exact_noop_returns_concurrently_replaced_api_key_preview(
    client: TestClient,
    monkeypatch,
    provider_kind: str,
) -> None:
    _cache_cloud_model()
    initial_payload = {
        "provider": "openai",
        "providerKind": provider_kind,
        "apiFamily": (
            "openai_responses" if provider_kind == "cloud" else "openai_compatible_chat"
        ),
        "nickname": "Original",
        "apiKey": "old-secret",
        "model": "gpt-test",
        "apiUrl": "https://api.openai.com/v1",
        "temperature": 0.4,
        "topP": 0.9,
        "maxTokens": 1_000,
    }
    created = client.post("/api/model-configs", json=initial_payload)
    assert created.status_code == 200
    config_id = created.json()["data"]["id"]
    both_requests_read_old_key = Barrier(2)
    key_update_committed = Event()
    original_build_values = model_configs._build_upsert_values

    def synchronize_after_read(item, existing):
        values = original_build_values(item, existing)
        both_requests_read_old_key.wait(timeout=5)
        if not item.api_key:
            assert key_update_committed.wait(timeout=5)
        return values

    monkeypatch.setattr(
        model_configs,
        "_build_upsert_values",
        synchronize_after_read,
    )
    second_client = TestClient(client.app, headers=dict(client.headers))

    def replace_key():
        try:
            return client.post(
                "/api/model-configs",
                json={
                    **initial_payload,
                    "id": config_id,
                    "apiKey": "new-secret",
                },
            )
        finally:
            key_update_committed.set()

    def exact_noop_without_key():
        return second_client.post(
            "/api/model-configs",
            json={
                **initial_payload,
                "id": config_id,
                "apiKey": None,
            },
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            key_future = executor.submit(replace_key)
            noop_future = executor.submit(exact_noop_without_key)
            key_response = key_future.result()
            noop_response = noop_future.result()
    finally:
        second_client.close()

    assert key_response.status_code == 200
    assert noop_response.status_code == 200
    assert noop_response.json()["data"]["apiKeyPreview"] == "new-se****"
