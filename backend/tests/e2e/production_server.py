import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from tests.e2e.conftest import (
    BACKEND_ROOT,
    FRONTEND_ROOT,
    _stop_process,
    _unused_port,
    _wait_for_url,
)
from tests.runtime_environment import runtime_environment


class ProductionServer:
    def __init__(self, directory: Path) -> None:
        self.image = os.environ.get("E2E_CONTAINER_IMAGE")
        self.name = f"reseno-e2e-{uuid4().hex}"
        self.data_dir = directory / "data"
        self.log_path = directory / "server.log"
        self.port = _unused_port()
        self.url = f"http://127.0.0.1:{self.port}"
        if self.image:
            self._docker("volume", "create", self.name)

    @contextmanager
    def running(self) -> Iterator[None]:
        env = os.environ.copy()
        if self.image:
            command = [
                "docker",
                "run",
                "--rm",
                "--name",
                self.name,
                "--publish",
                f"127.0.0.1:{self.port}:8000",
                "--volume",
                f"{self.name}:/data",
                self.image,
            ]
        else:
            dist = FRONTEND_ROOT / "dist"
            assert (dist / "index.html").is_file(), (
                "Build the frontend before this test."
            )
            env.update(
                {
                    **runtime_environment(self.data_dir),
                    "FRONTEND_DIST_DIR": str(dist),
                    "FRONTEND_RENDER_BASE_URL": self.url,
                    "BACKEND_CORS_ORIGINS": "",
                }
            )
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--workers",
                "1",
            ]
        with self.log_path.open("a+", encoding="utf-8") as log:
            process = subprocess.Popen(
                command, cwd=BACKEND_ROOT, env=env, stdout=log, stderr=log, text=True
            )
            try:
                _wait_for_url(f"{self.url}/health", process, log)
                if self.image:
                    assert int(self._docker("exec", self.name, "id", "-u")) > 0
                    healthcheck = json.loads(
                        self._docker(
                            "inspect",
                            "--format",
                            "{{json .Config.Healthcheck}}",
                            self.name,
                        )
                    )
                    assert healthcheck and healthcheck["Test"][0] == "CMD"
                    self._docker("exec", self.name, *healthcheck["Test"][1:])
                yield
            finally:
                try:
                    if self.image:
                        subprocess.run(
                            ["docker", "stop", "--time", "5", self.name],
                            capture_output=True,
                            timeout=15,
                            check=False,
                        )
                finally:
                    _stop_process(process)

    def keys_digest(self) -> str:
        if self.image:
            return self._docker(
                "exec",
                self.name,
                "python",
                "-c",
                "import hashlib; from pathlib import Path; "
                "print(hashlib.sha256(Path('/data/.env').read_bytes()).hexdigest())",
            )
        return hashlib.sha256((self.data_dir / ".env").read_bytes()).hexdigest()

    def setup_container_owner(self, credentials: dict[str, str]) -> None:
        self._docker(
            "exec",
            "-i",
            self.name,
            "python",
            "-c",
            "import json, sys, httpx; "
            "response = httpx.post('http://127.0.0.1:8000/api/auth/setup', "
            "json=json.load(sys.stdin), trust_env=False, timeout=10); "
            "response.raise_for_status()",
            input_text=json.dumps(
                {**credentials, "confirmPassword": credentials["password"]}
            ),
        )

    def remove_volume(self) -> None:
        if self.image:
            subprocess.run(
                ["docker", "rm", "--force", self.name],
                capture_output=True,
                timeout=15,
                check=False,
            )
            self._docker("volume", "rm", self.name)

    @staticmethod
    def _docker(*args: str, input_text: str | None = None) -> str:
        result = subprocess.run(
            ["docker", *args],
            input=input_text,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()
