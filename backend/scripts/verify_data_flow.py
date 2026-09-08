import os
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="reseno-data-flow-") as tmp_dir:
        data_dir = Path(tmp_dir)
        from tests.runtime_environment import runtime_environment

        os.environ.update(runtime_environment(data_dir))

        from fastapi.testclient import TestClient

        from app.config import get_settings
        from app.main import create_app

        with TestClient(
            create_app(),
            client=("127.0.0.1", 50000),
        ) as client:
            setup = client.post(
                "/api/auth/setup",
                json={
                    "username": "admin",
                    "password": "ScriptPassword2026",
                    "confirmPassword": "ScriptPassword2026",
                },
            )
            assert setup.status_code == 200
            assert "ScriptPassword2026" not in setup.text
            access_token = setup.json()["data"]["accessToken"]
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
                    "documentLocale": "en",
                    "title": "Script Resume",
                    "jobBrief": "Data flow",
                    "typography": {"fontFamily": "inter", "fontSize": 16},
                    "template": "minimal",
                    "resume": {
                        "schemaVersion": 2,
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
            assert resume_saved.json()["code"] == 0, resume_saved.text
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
                data_dir / "storage" / "resumes" / resume_id / "versions" / "1.json"
            ).exists()

            db_bytes = (data_dir / "app.db").read_bytes()
            assert b"sk-script-workspace-secret" not in db_bytes
            settings = get_settings()
            env_bytes = settings.env_file_path.read_bytes()
            assert set(dotenv_values(settings.env_file_path, interpolate=False)) == {
                "RESENO_MASTER_KEY", "RESENO_JWT_SECRET",
            }
            assert b"sk-script-workspace-secret" not in env_bytes

        print("Backend data flow verified.")


if __name__ == "__main__":
    main()
