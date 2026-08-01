import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="resumate-data-flow-") as tmp_dir:
        data_dir = Path(tmp_dir)
        os.environ["APP_DATA_DIR"] = str(data_dir)
        os.environ["APP_DB_PATH"] = str(data_dir / "app.db")
        os.environ["APP_STORAGE_DIR"] = str(data_dir / "storage")
        os.environ["APP_ENV_FILE"] = str(data_dir / ".env")
        os.environ["APP_ENV"] = "production"
        os.environ["AUTH_USERNAME"] = "admin"
        os.environ["AUTH_PASSWORD"] = "ResuMate@2026"

        from fastapi.testclient import TestClient

        from app.main import create_app

        with TestClient(create_app()) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "ResuMate@2026"},
            )
            assert login.status_code == 200
            assert "ResuMate@2026" not in login.text
            access_token = login.json()["data"]["accessToken"]
            client.headers.update({"Authorization": f"Bearer {access_token}"})

            model_saved = client.post(
                "/api/model-configs",
                json={
                    "id": "llm-script",
                    "provider": "openai",
                    "providerKind": "custom",
                    "apiFamily": "openai_compatible_chat",
                    "nickname": "Script",
                    "apiKey": "sk-script-workspace-secret",
                    "model": "gpt-5.1",
                    "apiUrl": "https://api.openai.com/v1",
                    "temperature": 0.4,
                    "topP": 0.9,
                    "maxTokens": None,
                },
            )
            assert model_saved.status_code == 200

            resume_saved = client.post(
                "/api/resumes",
                json={
                    "title": "Script Resume",
                    "jobBrief": "Data flow",
                    "typography": {"fontFamily": "inter", "fontSize": 16},
                    "template": "minimal",
                    "resume": {
                        "basic": {
                            "name": "Script Resume",
                            "headline": "",
                            "phone": "",
                            "email": "",
                            "location": "",
                            "avatar": "",
                            "summary": "",
                            "customFields": [],
                        },
                        "sections": [],
                    },
                },
            )
            assert resume_saved.status_code == 200
            resume_id = resume_saved.json()["data"]["resume"]["id"]

            models_page = client.get("/api/workspace/pages/models")
            assert models_page.status_code == 200
            assert "resumes" not in models_page.json()["data"]
            model_config = models_page.json()["data"]["modelConfigs"][0]
            assert "apiKey" not in model_config
            assert "apiKeyEnvName" not in model_config
            assert model_config["apiKeyPreview"] == "sk-scr****"

            resumes = client.get("/api/resumes")
            assert resumes.status_code == 200
            assert resumes.json()["data"]["resumes"][0]["id"] == resume_id

            versions = client.get(f"/api/resumes/{resume_id}/versions")
            assert versions.status_code == 200
            assert versions.json()["data"]["versions"]
            assert (
                data_dir
                / "storage"
                / "resumes"
                / resume_id
                / "versions"
                / "1.json"
            ).exists()

            db_bytes = (data_dir / "app.db").read_bytes()
            assert b"sk-script-workspace-secret" not in db_bytes
            env_bytes = (data_dir / ".env").read_bytes()
            assert b"RESUMATE_MASTER_KEY=" in env_bytes
            assert b"RESUMATE_JWT_SECRET=" in env_bytes
            assert b"sk-script-workspace-secret" not in env_bytes

        print("Backend data flow verified.")


if __name__ == "__main__":
    main()
