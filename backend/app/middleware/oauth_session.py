from starlette.middleware.sessions import SessionMiddleware
from starlette.types import Message, Receive, Scope, Send


class OAuthSessionMiddleware(SessionMiddleware):
    """Sign OAuth sessions and secure cookies for their validated browser origin."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_with_cookie_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                origin = scope.get("session", {}).get("public_base_url") or scope.get(
                    "state", {}
                ).get("oauth_public_base_url", "")
                if not origin.startswith("http://"):
                    message["headers"] = [
                        (
                            name,
                            value + b"; secure"
                            if name.lower() == b"set-cookie"
                            and value.startswith(f"{self.session_cookie}=".encode())
                            else value,
                        )
                        for name, value in message.get("headers", [])
                    ]
            await send(message)

        await super().__call__(scope, receive, send_with_cookie_policy)
