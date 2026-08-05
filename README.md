# odoo-bookkeeping-mcp

An MCP (Model Context Protocol) server that gives an LLM agent -- Claude,
ChatGPT, or any other MCP-compatible client -- full read/write access to one
Odoo instance's accounting (invoices, vendor bills, journal entries,
payments, reconciliation, P&L/balance sheet/aged reports) and, if the
instance has the `project_budget_boq_sunderland` addon installed, its
BOQ/Project Budget data.

It is **not** an Odoo addon. It talks to Odoo the same way any external
integration does: Odoo's standard `/xmlrpc/2/*` API, authenticated as a
normal Odoo user via an API key. No code needs to be installed on the Odoo
server.

## ⚠️ Read this before pointing it at a real database

This server was built with **no restrictions by explicit request**: every
tool that can create, edit, post, or reconcile a real accounting record
will do so immediately when called, with no draft/review/approval gate and
no human-in-the-loop step. That is a deliberate choice, not an oversight --
but it means:

- **A wrong or hallucinated tool call becomes a real entry in your books.**
  A posted journal entry cannot be edited or un-posted -- correcting it
  needs a reversal or credit note (this server can do that too, but the
  original mistake still shows up in every report until it's reversed).
- **Whoever/whatever can reach this server can act as its Odoo user.**
  Give it a **dedicated Odoo user** (not an admin's personal login) scoped
  to exactly the access rights, companies, and record rules you want an
  agent to have -- Odoo's own security model is still the only thing
  standing between "the agent read this wrong" and "the books are wrong."
- **Deletion (`odoo_unlink`) is the one thing still off by default** --
  see `ODOO_MCP_ALLOW_UNLINK` below. Everything else (create/write/post/
  reconcile) is on by default per the request that led to this server.
- Treat the `.env` file / API key like a production database password,
  because functionally it is one.

## What's inside

```
src/odoo_mcp/
  client.py     Odoo XML-RPC wrapper (auth, generic CRUD, error mapping)
  config.py     Reads connection + safety-valve settings from the environment
  server.py     MCP server entrypoint; registers every tool module below;
               dispatches to stdio or HTTP transport
  http_auth.py  Bearer-token ASGI middleware, used only in HTTP transport
  tools/
    generic.py     odoo_search_read / odoo_create / odoo_write / odoo_unlink /
                   odoo_call_method / odoo_fields_get -- works against ANY
                   model, the "no restrictions" escape hatch every other
                   tool module is really just a friendlier wrapper over.
    accounting.py   Customer invoices, vendor bills, journal entries,
                   posting, reversal, payment registration, reconciliation.
    reports.py      P&L, balance sheet, trial balance, general ledger,
                   aged receivable/payable -- computed from posted
                   account.move.line data (not Odoo's PDF report engine).
    boq.py          project.budget / project.budget.line: list/get budgets,
                   create/update BOQ lines, submit/approve/activate
                   workflow, budget-vs-actual. Only useful if your Odoo
                   instance has project_budget_boq_sunderland installed;
                   otherwise fall back to the generic tools for whatever
                   budgeting model it does have.
tests/           Unit tests against a mocked XML-RPC server (no live Odoo
                 instance is available while building this) -- verify
                 request shaping, auth caching, and error handling. They do
                 NOT prove your specific Odoo instance/version behaves
                 identically; test against a real (ideally staging) database
                 before trusting this in production.
```

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# edit .env with your real Odoo URL / DB / username / API key
python -m pytest tests/ -v
```

### Getting an Odoo API key

In Odoo: click your avatar → **My Profile** → **Account Security** → **New
API Key**. Do this for the **dedicated integration user** you created for
this server, not your own login.

### Environment variables

See `.env.example` for the full list with comments. Required:
`ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_API_KEY`.

Safety valves (optional, all env-var controlled so you never need to edit
code to change them):

| Variable | Default | Gates |
|---|---|---|
| `ODOO_MCP_ALLOW_UNLINK` | `false` | `odoo_unlink` (permanent record deletion) |
| `ODOO_MCP_ALLOW_POST` | `true` | posting invoices/journal entries, registering payments |
| `ODOO_MCP_ALLOW_RECONCILE` | `true` | `reconcile_lines` |

Transport (optional):

| Variable | Default | Notes |
|---|---|---|
| `ODOO_MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `ODOO_MCP_BEARER_TOKEN` | *(none)* | **required** when `ODOO_MCP_TRANSPORT=http` -- server refuses to start over HTTP without it |
| `ODOO_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `ODOO_MCP_PORT` | `8000` | HTTP bind port |

## Connecting it to Claude

**Claude Desktop / Claude Code** -- add to your MCP config
(`claude_desktop_config.json` or the CLI's `.mcp.json`):

```json
{
  "mcpServers": {
    "odoo-bookkeeping": {
      "command": "odoo-mcp",
      "env": {
        "ODOO_URL": "https://your-instance.odoo.com",
        "ODOO_DB": "your-db",
        "ODOO_USERNAME": "mcp-integration@yourcompany.com",
        "ODOO_API_KEY": "your-api-key"
      }
    }
  }
}
```

(Run `pip install -e .` first so the `odoo-mcp` command exists on PATH, or
use the full path to `python -m odoo_mcp.server` instead of `odoo-mcp`.)

## Running it on a server (HTTP transport, for ChatGPT or remote access)

ChatGPT's MCP/connector support (and any remote Claude session) needs a
server reachable over HTTP, not a local stdio process. Set the transport
and a bearer token, then run it:

```bash
export ODOO_MCP_TRANSPORT=http
export ODOO_MCP_BEARER_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo "Save this token -- callers must send it as: Authorization: Bearer $ODOO_MCP_BEARER_TOKEN"
odoo-mcp
# or: python -m odoo_mcp.server
```

This serves `POST /mcp` (streamable-HTTP) on `ODOO_MCP_HOST:ODOO_MCP_PORT`
(default `127.0.0.1:8000`), gated by a self-contained ASGI middleware
(`http_auth.py`) that rejects any request without an exact
`Authorization: Bearer <token>` match -- **the server refuses to start
over HTTP at all if `ODOO_MCP_BEARER_TOKEN` is unset**, since this server
has no other access control of its own.

Before pointing a real client at it:

- **Keep the bind address at `127.0.0.1`** and put a reverse proxy
  (nginx, Caddy, Cloudflare Tunnel) in front for TLS + a real domain --
  this process speaks plain HTTP and does not terminate TLS itself.
- The bearer token is the *entire* network-facing security boundary here
  (Odoo's own access rights are the boundary behind it). Rotate it if it
  ever leaks, and don't put it in a URL, query string, or client-side
  code -- header only.
- Configure your MCP client (ChatGPT connector settings, or a remote
  Claude MCP config) to call `https://your-domain/mcp` with that bearer
  token as its auth header.

## What is NOT here

- No Odoo module/addon changes -- this only uses Odoo's existing external
  API, so it works against any reasonably recent Odoo version without
  touching the target instance at all.
- No real Odoo test run -- this development environment has no reachable
  Odoo/Postgres instance. Everything above `tests/` is verified with a
  mocked XML-RPC backend (request shaping, auth, error handling) and a
  live tool-registration smoke test against the actual MCP server object;
  none of it has been exercised against a real database. Test against a
  staging Odoo database before pointing this at production.
- No UI, no scheduling, no webhook listener -- it only responds to tool
  calls a connected MCP client makes.
