"""Tests for the bearer-token ASGI middleware that gates HTTP transport.

This is the entire network-facing security boundary for the HTTP mode of
this server, so it gets tested directly rather than only indirectly
through server.py.
"""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from odoo_mcp.http_auth import BearerAuthMiddleware

TOKEN = "test-secret-token-zzz"


async def _ok(request):
    return PlainTextResponse("ok")


def _protected_client():
    inner = Starlette(routes=[Route("/mcp", _ok)])
    protected = BearerAuthMiddleware(inner, TOKEN)
    return TestClient(protected)


def test_rejects_missing_authorization_header():
    client = _protected_client()
    resp = client.get("/mcp")
    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_rejects_wrong_token():
    client = _protected_client()
    resp = client.get("/mcp", headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


def test_rejects_non_bearer_scheme():
    client = _protected_client()
    resp = client.get("/mcp", headers={"Authorization": f"Basic {TOKEN}"})
    assert resp.status_code == 401


def test_accepts_correct_token():
    client = _protected_client()
    resp = client.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_www_authenticate_header_present_on_rejection():
    client = _protected_client()
    resp = client.get("/mcp")
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_empty_token_refuses_to_construct():
    inner = Starlette(routes=[Route("/mcp", _ok)])
    with pytest.raises(ValueError):
        BearerAuthMiddleware(inner, "")
