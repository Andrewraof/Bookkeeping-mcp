"""Bearer-token authentication in front of the MCP streamable-HTTP app.

FastMCP's built-in `auth=`/`token_verifier` hooks are built for full OAuth
2.1 resource-server flows (they require a real ``issuer_url``) -- overkill
for "gate this network port with one shared secret". This is a small,
fully self-contained raw ASGI middleware instead, so its behavior is easy
to read end-to-end and does not depend on any OAuth infrastructure
existing anywhere.

A raw ASGI middleware (not Starlette's BaseHTTPMiddleware) is used
deliberately: BaseHTTPMiddleware buffers the response, which breaks
streamable-HTTP's long-lived streaming responses.
"""
import hmac

from starlette.responses import JSONResponse


class BearerAuthMiddleware:
    """Rejects any HTTP request whose ``Authorization: Bearer <token>``
    header does not match the configured token exactly (constant-time
    compare). Only wraps ``http`` scopes -- ``lifespan`` events (startup/
    shutdown) pass straight through untouched."""

    def __init__(self, app, token: str):
        if not token:
            raise ValueError(
                "BearerAuthMiddleware requires a non-empty token -- "
                "refusing to build a middleware that would accept anything.")
        self.app = app
        self.token = token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth_header = headers.get(b"authorization", b"").decode("latin-1")
        provided = ""
        if auth_header.lower().startswith("bearer "):
            provided = auth_header[7:].strip()

        if not provided or not hmac.compare_digest(provided, self.token):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401,
                headers={"WWW-Authenticate": "Bearer"})
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
