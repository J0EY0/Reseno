import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.services.llm.common import chat_completion_params
from app.services.llm.config import resolve_agent_llm_config
from app.services.llm.types import LlmPrompt
from app.services.model_discovery_cache import write_cached_provider_models
from app.services.model_providers import DiscoveredModel


def _payload(provider: str = "ollama") -> dict[str, Any]:
    return {
        "provider": provider,
        "providerKind": "local",
        "apiFamily": "openai_compatible_chat",
        "apiUrl": "http://127.0.0.1:11434/v1",
        "model": "local-test-model",
        "contextWindowTokens": 32_768,
        "supportsThinking": True,
        "supportsTools": True,
    }


def _assert_runtime_sampling(
    config_id: str,
    temperature: float | None,
    top_p: float | None,
) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT temperature, top_p FROM llm_configs WHERE client_id = ?",
            (config_id,),
        ).fetchone()
        assert row is not None
        assert row["temperature"] == temperature
        assert row["top_p"] == top_p
        config = resolve_agent_llm_config(conn, config_id)
    assert config is not None
    assert config.temperature == temperature
    assert config.top_p == top_p
    prompt = LlmPrompt(messages=[{"role": "user", "content": "Review this resume."}])
    for stream in (False, True):
        params = chat_completion_params(config, prompt, stream=stream)
        assert params["stream"] is stream
        for key, expected in (("temperature", temperature), ("top_p", top_p)):
            if expected is None:
                assert key not in params
            else:
                assert params[key] == expected


@pytest.mark.parametrize("provider", ["ollama", "vllm", "sglang"])
def test_local_sampling_survives_save_reload_update_and_request_projection(
    client: TestClient,
    provider: str,
) -> None:
    payload = {**_payload(provider), "temperature": 0, "topP": 0.8765}
    created = client.post("/api/model-configs", json=payload)
    assert created.status_code == 200
    saved = created.json()["data"]
    assert saved["temperature"] == 0
    assert saved["topP"] == 0.8765
    _assert_runtime_sampling(saved["id"], 0, 0.8765)

    updated = client.post(
        "/api/model-configs",
        json={**payload, "id": saved["id"], "temperature": 1.234, "topP": 1},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["temperature"] == 1.234
    listed = client.get("/api/model-configs").json()["data"]["configs"]
    assert listed == [updated.json()["data"]]
    _assert_runtime_sampling(saved["id"], 1.234, 1)

    cleared = client.post(
        "/api/model-configs",
        json={**payload, "id": saved["id"], "temperature": None, "topP": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["temperature"] is None
    assert cleared.json()["data"]["topP"] is None
    _assert_runtime_sampling(saved["id"], None, None)


@pytest.mark.parametrize("provider", ["ollama", "vllm", "sglang"])
def test_local_sampling_omitted_fields_delegate_to_service_defaults(
    client: TestClient,
    provider: str,
) -> None:
    response = client.post("/api/model-configs", json=_payload(provider))
    assert response.status_code == 200
    _assert_runtime_sampling(response.json()["data"]["id"], None, None)


def test_local_sampling_accepts_upper_temperature_boundary(client: TestClient) -> None:
    response = client.post(
        "/api/model-configs",
        json={**_payload(), "temperature": 2, "topP": 0.0001},
    )
    assert response.status_code == 200
    _assert_runtime_sampling(response.json()["data"]["id"], 2, 0.0001)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("temperature", -0.001),
        ("temperature", 2.001),
        ("topP", 0),
        ("topP", -0.001),
        ("topP", 1.001),
        ("temperature", "NaN"),
        ("topP", "Infinity"),
        ("topP", "-Infinity"),
    ],
)
def test_invalid_local_sampling_update_preserves_existing_config(
    client: TestClient,
    field: str,
    invalid: Any,
) -> None:
    payload = {**_payload(), "temperature": 0.6, "topP": 0.95}
    created = client.post("/api/model-configs", json=payload)
    saved = created.json()["data"]
    rejected = client.post(
        "/api/model-configs",
        json={**payload, "id": saved["id"], field: invalid},
    )
    assert rejected.status_code == 422
    body = rejected.json()
    assert body["message"] == "VALIDATION_ERROR"
    assert body["data"]["errors"][0]["loc"] == ["body", field]
    assert client.get("/api/model-configs").json()["data"]["configs"] == [saved]
    _assert_runtime_sampling(saved["id"], 0.6, 0.95)


@pytest.mark.parametrize("field", ["temperature", "topP"])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_sampling_returns_serializable_validation_error(
    client: TestClient,
    field: str,
    invalid: float,
) -> None:
    response = client.post(
        "/api/model-configs",
        content=json.dumps({**_payload(), field: invalid}),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["message"] == "VALIDATION_ERROR"
    error = body["data"]["errors"][0]
    assert error["loc"] == ["body", field]
    assert isinstance(error["input"], str)
    assert client.get("/api/model-configs").json()["data"]["configs"] == []


def test_custom_sampling_keeps_existing_unrestricted_behavior(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/model-configs",
        json={
            **_payload(),
            "provider": "custom-cloud",
            "providerKind": "custom",
            "temperature": 3.5,
            "topP": 0,
        },
    )
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["temperature"] == 3.5 and saved["topP"] == 0
    _assert_runtime_sampling(saved["id"], 3.5, 0)


def test_cloud_sampling_keeps_existing_omission_behavior(client: TestClient) -> None:
    write_cached_provider_models(
        "openai",
        [
            DiscoveredModel(
                id="cloud-test-model",
                label="Cloud test",
                context_window_tokens=32_768,
                max_output_tokens=8_192,
                supports_image=False,
                thinking_control="none",
                metadata_source="provider",
            ),
        ],
    )
    response = client.post(
        "/api/model-configs",
        json={
            **_payload(),
            "provider": "openai",
            "providerKind": "cloud",
            "apiFamily": "openai_responses",
            "apiUrl": "https://api.openai.com/v1",
            "apiKey": "test-only-secret",
            "model": "cloud-test-model",
            "temperature": 3.5,
            "topP": 0,
        },
    )
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["temperature"] is None and saved["topP"] is None
