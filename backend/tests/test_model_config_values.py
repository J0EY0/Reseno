from fastapi.testclient import TestClient


def test_model_config_roundtrip_retains_each_editable_field(
    client: TestClient,
) -> None:
    payload = {
        "provider": "custom-cloud",
        "providerKind": "custom",
        "apiFamily": "anthropic_messages",
        "nickname": "Detailed model",
        "model": "custom-model",
        "apiUrl": "https://provider.invalid/v1",
        "apiKey": "test-only-secret",
        "temperature": 0.25,
        "topP": 0.85,
        "maxTokens": 3_072,
        "contextWindowTokens": 96_000,
        "supportsImage": True,
        "supportsThinking": True,
        "thinkingMode": "auto",
        "supportsTools": False,
        "supportsStreaming": True,
    }
    created = client.post("/api/model-configs", json=payload)
    assert created.status_code == 200
    first = created.json()["data"]
    for key, value in payload.items():
        if key != "apiKey":
            assert first[key] == value
    assert first["apiKeyPreview"]
    assert "apiKey" not in first

    updated_payload = {
        **payload,
        "id": first["id"],
        "nickname": "Adjusted model",
        "model": "custom-model-v2",
        "temperature": None,
        "topP": 0.65,
        "maxTokens": None,
        "contextWindowTokens": 192_000,
        "supportsImage": False,
        "supportsThinking": False,
        "supportsTools": True,
        "supportsStreaming": False,
        "apiKey": None,
    }
    updated = client.post("/api/model-configs", json=updated_payload)
    assert updated.status_code == 200
    second = updated.json()["data"]
    for key, value in updated_payload.items():
        if key != "apiKey":
            assert second[key] == value
    assert second["apiKeyPreview"] == first["apiKeyPreview"]

    repeated = client.post("/api/model-configs", json=updated_payload)
    assert repeated.status_code == 200
    assert repeated.json()["data"] == second
    listed = client.get("/api/model-configs")
    assert listed.status_code == 200
    assert listed.json()["data"]["configs"] == [second]
