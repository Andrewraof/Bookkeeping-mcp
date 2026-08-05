"""Generic, unrestricted tools: search/read/create/write/unlink/call any
method on any Odoo model the connected user can access.

These are the "no restrictions" escape hatch -- every domain-specific tool
in accounting.py / reports.py / boq.py is really just a friendlier wrapper
over these same primitives. Anything Odoo's own external API can do, these
tools can do too, scoped only by the access rights of the Odoo user the
server authenticates as.
"""
from ..client import OdooClient, OdooError
from ..config import OdooConfig


def register(mcp, client: OdooClient, config: OdooConfig) -> None:

    @mcp.tool()
    def odoo_search_read(model: str, domain: list = None, fields: list = None,
                         limit: int = 80, offset: int = 0,
                         order: str = None) -> dict:
        """Search and read records of ANY Odoo model in one call.

        model: technical model name, e.g. "account.move", "res.partner",
            "project.budget.line".
        domain: Odoo domain, e.g. [["state", "=", "draft"]]. Empty/omitted
            matches all records (subject to record rules).
        fields: field names to return; omit for all fields.
        limit: max records to return (default 80, use 0 for no limit --
            careful on large models).
        order: e.g. "date desc, id desc".
        """
        try:
            records = client.search_read(
                model, domain=domain or [], fields=fields,
                limit=limit or None, offset=offset, order=order)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}

    @mcp.tool()
    def odoo_fields_get(model: str) -> dict:
        """List every field on an Odoo model: type, label, required,
        readonly, relation target, selection options. Use this before
        create/write on an unfamiliar model instead of guessing field names.
        """
        try:
            return client.fields_get(model)
        except OdooError as exc:
            return {"error": str(exc)}

    @mcp.tool()
    def odoo_create(model: str, values: dict) -> dict:
        """Create ONE record on any model. Returns the new record's id.

        Example: odoo_create("res.partner", {"name": "Acme LLC"}).
        For accounting documents prefer the dedicated accounting.* tools
        (they set up lines/taxes/journals correctly) -- use this for
        anything they don't cover.
        """
        try:
            new_id = client.create(model, values)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"id": new_id, "model": model}

    @mcp.tool()
    def odoo_write(model: str, ids: list, values: dict) -> dict:
        """Update one or more existing records with the given field values.
        """
        try:
            client.write(model, ids, values)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "model": model, "ids": ids}

    @mcp.tool()
    def odoo_unlink(model: str, ids: list) -> dict:
        """Permanently delete one or more records. THIS CANNOT BE UNDONE.

        Disabled by default (ODOO_MCP_ALLOW_UNLINK=false) because Odoo has
        no "undo" for a deleted record -- unlike posted accounting entries,
        which can always be reversed with a credit note / reversal entry.
        Set ODOO_MCP_ALLOW_UNLINK=true in the server's environment to allow
        this tool to actually delete anything.
        """
        if not config.allow_unlink:
            return {
                "error": (
                    "Deletion is disabled on this server "
                    "(ODOO_MCP_ALLOW_UNLINK is not set to true). "
                    "Odoo itself will refuse to delete most posted "
                    "accounting records anyway -- use a reversal/credit "
                    "note instead of asking for this to be re-enabled."),
            }
        try:
            client.unlink(model, ids)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "model": model, "deleted_ids": ids}

    @mcp.tool()
    def odoo_call_method(model: str, method: str, ids: list = None,
                         args: list = None, kwargs: dict = None) -> dict:
        """Call ANY method on an Odoo model -- the universal escape hatch.

        Use this for workflow actions the dedicated tools don't wrap yet,
        e.g. odoo_call_method("account.move", "button_draft", [123]) or
        odoo_call_method("project.budget", "action_approve", [7]).
        ids may be empty for @api.model methods that don't act on records.
        """
        try:
            result = client.call_method(
                model, method, ids or [], *(args or []), **(kwargs or {}))
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "result": result}
