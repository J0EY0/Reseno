from fastapi.testclient import TestClient

from app.db.connection import connect


def _create_model_config(client: TestClient, name: str) -> str:
    response = client.post(
        "/api/model-configs",
        json={
            "provider": "openai",
            "providerKind": "custom",
            "apiFamily": "openai_compatible_chat",
            "nickname": name,
            "model": f"model-{name}",
            "apiUrl": "https://example.com/v1",
            "contextWindowTokens": 16_384,
        },
    )

    assert response.status_code == 200
    return response.json()["data"]["id"]


def _enabled_by_id(*config_ids: str) -> dict[str, int]:
    placeholders = ", ".join("?" for _ in config_ids)
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT client_id, enabled
            FROM llm_configs
            WHERE client_id IN ({placeholders})
            """,
            config_ids,
        ).fetchall()

    return {row["client_id"]: row["enabled"] for row in rows}


def test_bulk_delete_soft_deletes_requested_model_configs(
    client: TestClient,
) -> None:
    first_id = _create_model_config(client, "first")
    second_id = _create_model_config(client, "second")
    remaining_id = _create_model_config(client, "remaining")

    response = client.post(
        "/api/model-configs/bulk-delete",
        json={"ids": [first_id, second_id]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {"ids": [first_id, second_id]}
    assert _enabled_by_id(first_id, second_id, remaining_id) == {
        first_id: 0,
        second_id: 0,
        remaining_id: 1,
    }
    listed_ids = {
        item["id"]
        for item in client.get("/api/model-configs").json()["data"]["configs"]
    }
    assert listed_ids == {remaining_id}


def test_bulk_delete_rejects_an_empty_id_list(client: TestClient) -> None:
    response = client.post(
        "/api/model-configs/bulk-delete",
        json={"ids": []},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "VALIDATION_ERROR"


def test_bulk_delete_rejects_duplicate_ids_without_deleting(
    client: TestClient,
) -> None:
    config_id = _create_model_config(client, "duplicate")

    response = client.post(
        "/api/model-configs/bulk-delete",
        json={"ids": [config_id, config_id]},
    )

    assert response.status_code == 422
    assert response.json()["message"] == "VALIDATION_ERROR"
    assert _enabled_by_id(config_id) == {config_id: 1}


def test_bulk_delete_rolls_back_when_any_id_does_not_exist(
    client: TestClient,
) -> None:
    first_id = _create_model_config(client, "rollback-first")
    second_id = _create_model_config(client, "rollback-second")

    response = client.post(
        "/api/model-configs/bulk-delete",
        json={"ids": [first_id, "llm-does-not-exist", second_id]},
    )

    assert response.status_code == 404
    assert response.json()["message"] == "MODEL_CONFIG_NOT_FOUND"
    assert _enabled_by_id(first_id, second_id) == {
        first_id: 1,
        second_id: 1,
    }


def test_bulk_delete_is_idempotent_for_existing_soft_deleted_ids(
    client: TestClient,
) -> None:
    already_deleted_id = _create_model_config(client, "already-deleted")
    active_id = _create_model_config(client, "active")
    single_delete = client.delete(f"/api/model-configs/{already_deleted_id}")

    response = client.post(
        "/api/model-configs/bulk-delete",
        json={"ids": [already_deleted_id, active_id]},
    )

    assert single_delete.status_code == 200
    assert response.status_code == 200
    assert response.json()["data"] == {
        "ids": [already_deleted_id, active_id],
    }
    assert _enabled_by_id(already_deleted_id, active_id) == {
        already_deleted_id: 0,
        active_id: 0,
    }
