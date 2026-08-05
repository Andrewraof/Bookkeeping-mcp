"""Odoo Bookkeeping MCP server entrypoint.

Run with: odoo-mcp   (after `pip install -e .`)
or:       python -m odoo_mcp.server
"""
import logging
import sys

from mcp.server.fastmcp import FastMCP

from .client import OdooClient
from .config import OdooConfig, OdooConfigError
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


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()
