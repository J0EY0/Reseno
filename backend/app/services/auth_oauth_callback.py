import json
import secrets

from fastapi.responses import HTMLResponse

from app.schemas.common import APP_MESSAGE_OAUTH_INVALID_STATE


def oauth_callback_response(origin: str, result: dict[str, str]) -> HTMLResponse:
    nonce = secrets.token_urlsafe(24)
    data = (
        json.dumps(
            {
                "origin": origin,
                "result": {"type": "reseno:oauth:result", **result},
                "errorUrl": (
                    f"{origin}/auth/callback#error={APP_MESSAGE_OAUTH_INVALID_STATE}"
                ),
            }
        )
        .replace("<", r"\u003c")
        .replace(">", r"\u003e")
        .replace("&", r"\u0026")
    )
    return HTMLResponse(
        f"""<!doctype html>
<html><head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<meta name="referrer" content="no-referrer">
<title>Reseno</title>
<style nonce="{nonce}">
:root {{ color-scheme: light dark; background: #f4f4f5; }}
@media (prefers-color-scheme: dark) {{ :root {{ background: #09090b; }} }}
body {{ margin: 0; }}
</style>
<script nonce="{nonce}">
(() => {{
  window.history.replaceState(window.history.state, "", window.location.pathname);
  const config = {data};
  const opener = window.opener;
  const fail = () => window.location.replace(config.errorUrl);
  if (!opener || !config.origin) {{
    fail();
    return;
  }}
  const timeout = window.setTimeout(() => {{
    window.removeEventListener("message", receive);
    fail();
  }}, 5000);
  function receive(event) {{
    if (event.origin !== config.origin || event.source !== opener ||
        event.data?.type !== "reseno:oauth:received") return;
    window.clearTimeout(timeout);
    window.removeEventListener("message", receive);
  }}
  window.addEventListener("message", receive);
  opener.postMessage(config.result, config.origin);
}})();
</script>
</head><body></body></html>""",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "base-uri 'none'; frame-ancestors 'none'; form-action 'none'"
            ),
        },
    )
