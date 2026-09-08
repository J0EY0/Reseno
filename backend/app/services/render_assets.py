import httpx
from anyio import fail_after
from anyio.from_thread import start_blocking_portal
from playwright.sync_api import Route

from app.services.agent.integrations.web_network import PublicWebTransport

MAX_RENDER_IMAGE_BYTES = 10 * 1024 * 1024


async def _fetch_public_image(url: str) -> tuple[bytes, str] | None:
    try:
        with fail_after(10):
            async with httpx.AsyncClient(
                transport=PublicWebTransport(),
                follow_redirects=True,
                max_redirects=5,
                trust_env=False,
                timeout=10,
            ) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if not content_type.lower().startswith("image/"):
                        return None
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RENDER_IMAGE_BYTES:
                            return None
                    return bytes(body), content_type
    except (httpx.HTTPError, TimeoutError, ValueError):
        return None


def route_render_image(route: Route) -> None:
    """Fetch remote images through validated connections without browser credentials."""

    if route.request.resource_type != "image":
        route.continue_()
        return
    with start_blocking_portal() as portal:
        image = portal.call(_fetch_public_image, route.request.url)
    if image is None:
        route.abort("blockedbyclient")
        return
    body, content_type = image
    route.fulfill(status=200, body=body, content_type=content_type)
