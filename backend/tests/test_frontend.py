from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

INDEX = "<!doctype html><html><body>Reseno</body></html>"


@pytest.fixture(autouse=True)
def frontend_dist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "main.js").write_text("console.log('Reseno');")
    (dist / "assets" / "main.css").write_text("body { margin: 0; }")
    (tmp_path / "private.txt").write_text("private contents")
    (dist / "private-link.txt").symlink_to(tmp_path / "private.txt")
    monkeypatch.setenv("FRONTEND_DIST_DIR", str(dist))
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "")
    return dist


@pytest.mark.parametrize("path", ["/", "/login", "/resume/example", "/index.html"])
def test_frontend_navigation_and_head(uninitialized_client: TestClient, path: str):
    response = uninitialized_client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"

    head = uninitialized_client.head(path, headers={"Accept": "text/html"})
    assert head.status_code == 200
    assert head.content == b""
    assert head.headers["content-length"] == response.headers["content-length"]

    conditional = uninitialized_client.get(
        path,
        headers={"Accept": "text/html", "If-None-Match": response.headers["etag"]},
    )
    assert conditional.status_code == 304
    assert conditional.headers["cache-control"] == "no-cache"


def test_frontend_home_without_accept_header(uninitialized_client: TestClient):
    uninitialized_client.headers.pop("accept", None)
    for method in ("GET", "HEAD"):
        response = uninitialized_client.request(method, "/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
        assert response.text == (INDEX if method == "GET" else "")


@pytest.mark.parametrize(
    ("path", "content_type", "content"),
    [
        ("/assets/main.js", "javascript", "console.log('Reseno');"),
        ("/assets/main.css", "text/css", "body { margin: 0; }"),
    ],
)
def test_frontend_assets(
    uninitialized_client: TestClient, path: str, content_type: str, content: str
):
    response = uninitialized_client.get(path)
    assert response.status_code == 200
    assert response.text == content
    assert content_type in response.headers["content-type"]


@pytest.mark.parametrize(
    "path",
    [
        "/assets/missing.js",
        "/assets/missing",
        "/missing.css",
        "/health/missing",
        "/api",
        "/api/missing",
        "/%2e%2e/private.txt",
        "/private-link.txt",
    ],
)
def test_missing_or_private_paths_stay_404(client: TestClient, path: str):
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "private contents" not in response.text
    assert INDEX not in response.text


def test_frontend_only_handles_html_navigation(uninitialized_client: TestClient):
    assert uninitialized_client.get("/resume/example").status_code == 404
    response = uninitialized_client.post(
        "/resume/example", headers={"Accept": "text/html"}
    )
    assert response.status_code == 405
    assert uninitialized_client.get("/health").json() == {"status": "ok"}
    assert uninitialized_client.get("/api/missing").status_code == 401


def test_frontend_is_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FRONTEND_DIST_DIR", "")
    assert get_settings().frontend_dist_dir is None
    with TestClient(create_app()) as client:
        assert client.get("/", headers={"Accept": "text/html"}).status_code == 404
        assert client.get("/health").status_code == 200


def test_frontend_requires_built_entry(frontend_dist: Path):
    (frontend_dist / "index.html").unlink()
    with pytest.raises(RuntimeError, match="FRONTEND_DIST_DIR must contain index.html"):
        create_app()


@pytest.mark.parametrize("host", ["localhost:9080", "resume.example.com"])
def test_same_origin_hosting_accepts_external_hosts(
    uninitialized_client: TestClient, host: str
):
    response = uninitialized_client.get(
        "/login", headers={"Host": host, "Accept": "text/html"}
    )
    assert response.status_code == 200
    assert get_settings().cors_origins == ()
    response = uninitialized_client.options(
        "/api/resumes",
        headers={
            "Host": host,
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_can_be_overridden(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BACKEND_CORS_ORIGINS", "https://frontend.example.com")
    with TestClient(create_app()) as client:
        response = client.options(
            "/api/resumes",
            headers={
                "Origin": "https://frontend.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "https://frontend.example.com"
        )


def test_unset_cors_origins_keep_development_defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BACKEND_CORS_ORIGINS")
    assert get_settings().cors_origins == (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
