"""Odoo Bookkeeping MCP server entrypoint.

Run with: odoo-mcp   (after `pip install -e .`)
or:       python -m odoo_mcp.server

Transport is chosen by ODOO_MCP_TRANSPORT (default "stdio"):
  stdio  -- local process spawned by Claude Desktop/Code. Not reachable
            over the network at all; no separate auth needed.
  http   -- streamable-HTTP server for remote/ChatGPT use. Requires
            ODOO_MCP_BEARER_TOKEN (fails closed otherwise -- see README).
"""
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from .client import OdooClient
from .config import OdooConfig, OdooConfigError
from .http_auth import BearerAuthMiddleware
from .tools import accounting, boq, generic, reports

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
_logger = logging.getLogger("odoo_mcp.server")


def build_server() -> FastMCP:
    try:
        config = OdooConfig.from_env()
    except OdooConfigError as exc:
        _logger.error(str(exc))
        raise

    client = OdooClient(config)
    mcp = FastMCP(
        "odoo-bookkeeping",
        instructions=(
            "Full-control bookkeeping and BOQ/Budget tools for one Odoo "
            "instance, connected as the configured Odoo user. Every tool "
            "acts with that user's real Odoo access rights -- nothing is "
            "simulated. Prefer the accounting.*/boq.* domain tools; fall "
            "back to odoo_create/odoo_write/odoo_call_method for anything "
            "not covered by a dedicated tool. Posted accounting entries "
            "cannot be edited -- use reverse_journal_entry / a credit note "
            "to correct them."
        ),
    )

    generic.register(mcp, client, config)
    accounting.register(mcp, client, config)
    reports.register(mcp, client, config)
    boq.register(mcp, client, config)

    return mcp


def run_http(server: FastMCP) -> None:
    """Serve the MCP app over streamable-HTTP, behind a bearer-token gate.

    Fails closed: with no internal restrictions of its own, this server
    must never listen on a network port with no auth in front of it.
    """
    import uvicorn

    token = os.environ.get("ODOO_MCP_BEARER_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "ODOO_MCP_BEARER_TOKEN must be set to run over HTTP -- this "
            "server has no internal restrictions, so an unauthenticated "
            "network port would let anyone reach your Odoo data. "
            "Generate one with: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    app = server.streamable_http_app()
    protected_app = BearerAuthMiddleware(app, token)

    host = os.environ.get("ODOO_MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("ODOO_MCP_PORT", "8000"))
    _logger.info("Serving streamable-HTTP on %s:%s (bearer-token protected)",
                host, port)
    config = uvicorn.Config(protected_app, host=host, port=port,
                            log_level="info")
    uvicorn.Server(config).run()


def main() -> None:
    server = build_server()
    transport = os.environ.get("ODOO_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        server.run()
    elif transport in ("http", "streamable-http"):
        run_http(server)
    else:
        raise RuntimeError(
            f"Unknown ODOO_MCP_TRANSPORT={transport!r}; use 'stdio' or 'http'.")


if __name__ == "__main__":
    main()
