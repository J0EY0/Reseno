from pathlib import Path

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope


class FrontendFiles(StaticFiles):
    """Serve production assets and HTML navigation for the frontend router."""

    def __init__(self, directory: Path) -> None:
        if not (directory / "index.html").is_file():
            raise RuntimeError("FRONTEND_DIST_DIR must contain index.html.")
        super().__init__(directory=directory, html=True)

    async def get_response(self, path: str, scope: Scope) -> Response:
        prefix = path.split("/", 1)[0]
        if prefix in {"api", "health"}:
            raise HTTPException(status_code=404)

        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if (
                exc.status_code != 404
                or scope["method"] not in {"GET", "HEAD"}
                or "text/html" not in Headers(scope=scope).get("accept", "")
                or Path(path).suffix
                or prefix in {"assets", ".."}
            ):
                raise
            path = "index.html"
            response = await super().get_response(path, scope)

        if path in {".", "index.html"}:
            response.headers["Cache-Control"] = "no-cache"
        return response
