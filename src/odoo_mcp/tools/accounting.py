"""Bookkeeping tools: customer invoices, vendor bills, journal entries,
payments and reconciliation -- built on top of account.move /
account.move.line, the same models Odoo's own Accounting app uses.

These are convenience wrappers: everything here can also be done through
generic.py's odoo_create/odoo_write/odoo_call_method. Use these when they
fit (they assemble line vals / call the right button_* methods correctly);
fall back to the generic tools for anything not covered here.
"""
from ..client import OdooClient, OdooError
from ..config import OdooConfig

_INVOICE_LINE_FIELDS = [
    "id", "name", "account_id", "quantity", "price_unit", "price_subtotal",
    "price_total", "tax_ids", "product_id", "analytic_distribution",
]
_MOVE_FIELDS = [
    "id", "name", "move_type", "state", "partner_id", "invoice_date",
    "date", "journal_id", "amount_untaxed", "amount_tax", "amount_total",
    "amount_residual", "currency_id", "ref", "narration", "payment_state",
]


def register(mcp, client: OdooClient, config: OdooConfig) -> None:

    # ── Customer invoices / vendor bills ────────────────────────────────
    @mcp.tool()
    def create_invoice(partner_id: int, lines: list, move_type: str = "out_invoice",
                       invoice_date: str = None, journal_id: int = None,
                       ref: str = None, currency_id: int = None,
                       company_id: int = None) -> dict:
        """Create a DRAFT customer invoice or vendor bill.

        move_type: "out_invoice" (customer invoice), "out_refund" (credit
            note), "in_invoice" (vendor bill), "in_refund" (vendor credit
            note).
        lines: list of dicts, each with at least "name" (description),
            "quantity", "price_unit". Optional per line: "product_id",
            "account_id", "tax_ids" (list of tax ids), "analytic_distribution"
            (e.g. {"<analytic_account_id>": 100.0}).
        Always created in draft -- call post_invoice() to post it once
        you're satisfied.
        """
        invoice_line_ids = []
        for line in lines:
            vals = {
                "name": line.get("name", ""),
                "quantity": line.get("quantity", 1.0),
                "price_unit": line.get("price_unit", 0.0),
            }
            if line.get("product_id"):
                vals["product_id"] = line["product_id"]
            if line.get("account_id"):
                vals["account_id"] = line["account_id"]
            if line.get("tax_ids"):
                vals["tax_ids"] = [(6, 0, line["tax_ids"])]
            if line.get("analytic_distribution"):
                vals["analytic_distribution"] = line["analytic_distribution"]
            invoice_line_ids.append((0, 0, vals))

        move_vals = {
            "move_type": move_type,
            "partner_id": partner_id,
            "invoice_line_ids": invoice_line_ids,
        }
        if invoice_date:
            move_vals["invoice_date"] = invoice_date
        if journal_id:
            move_vals["journal_id"] = journal_id
        if ref:
            move_vals["ref"] = ref
        if currency_id:
            move_vals["currency_id"] = currency_id
        if company_id:
            move_vals["company_id"] = company_id

        try:
            move_id = client.create("account.move", move_vals)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"id": move_id, "model": "account.move", "state": "draft"}

    @mcp.tool()
    def update_invoice(move_id: int, values: dict = None,
                       lines: list = None) -> dict:
        """Update a draft invoice/bill's header fields and/or replace its
        lines entirely. Odoo will reject this once the move is posted --
        use a reversal/credit note for posted documents instead.

        lines, if given, REPLACES all existing lines (same line-dict shape
        as create_invoice's `lines` argument).
        """
        vals = dict(values or {})
        if lines is not None:
            invoice_line_ids = [(5, 0, 0)]  # clear existing lines first
            for line in lines:
                line_vals = {
                    "name": line.get("name", ""),
                    "quantity": line.get("quantity", 1.0),
                    "price_unit": line.get("price_unit", 0.0),
                }
                if line.get("product_id"):
                    line_vals["product_id"] = line["product_id"]
                if line.get("account_id"):
                    line_vals["account_id"] = line["account_id"]
                if line.get("tax_ids"):
                    line_vals["tax_ids"] = [(6, 0, line["tax_ids"])]
                if line.get("analytic_distribution"):
                    line_vals["analytic_distribution"] = line["analytic_distribution"]
                invoice_line_ids.append((0, 0, line_vals))
            vals["invoice_line_ids"] = invoice_line_ids
        try:
            client.write("account.move", [move_id], vals)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": move_id}

    @mcp.tool()
    def post_invoice(move_id: int) -> dict:
        """Post (confirm) a draft invoice/vendor bill. Irreversible in the
        sense that a posted move must be reversed/credited, not edited, to
        correct it afterwards."""
        if not config.allow_post:
            return {"error": (
                "Posting is disabled on this server "
                "(ODOO_MCP_ALLOW_POST is not true).")}
        try:
            client.call_method("account.move", "action_post", [move_id])
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": move_id, "state": "posted"}

    @mcp.tool()
    def search_invoices(domain: list = None, limit: int = 80) -> dict:
        """Search customer invoices / vendor bills / credit notes. Example
        domain: [["move_type", "=", "in_invoice"], ["state", "=", "draft"]].
        """
        try:
            records = client.search_read(
                "account.move", domain=domain or [], fields=_MOVE_FIELDS,
                limit=limit, order="date desc, id desc")
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}

    @mcp.tool()
    def get_invoice(move_id: int) -> dict:
        """Full detail of one invoice/bill including its lines."""
        try:
            move = client.read("account.move", [move_id], fields=_MOVE_FIELDS)
            if not move:
                return {"error": f"account.move {move_id} not found"}
            move = move[0]
            line_ids = client.search_read(
                "account.move.line",
                domain=[["move_id", "=", move_id], ["display_type", "=", False]],
                fields=_INVOICE_LINE_FIELDS)
        except OdooError as exc:
            return {"error": str(exc)}
        move["lines"] = line_ids
        return move

    # ── Journal entries (manual, non-invoice moves) ─────────────────────
    @mcp.tool()
    def create_journal_entry(journal_id: int, date: str, lines: list,
                             ref: str = None, company_id: int = None) -> dict:
        """Create a DRAFT manual journal entry (move_type='entry').

        lines: list of dicts, each with "account_id" and either "debit" or
            "credit" (or both, defaulting to 0) plus optional "name"
            (label), "partner_id", "analytic_distribution". Must balance
            (total debit == total credit) -- Odoo enforces this on post.
        """
        line_ids = []
        for line in lines:
            vals = {
                "account_id": line["account_id"],
                "debit": line.get("debit", 0.0),
                "credit": line.get("credit", 0.0),
            }
            if line.get("name"):
                vals["name"] = line["name"]
            if line.get("partner_id"):
                vals["partner_id"] = line["partner_id"]
            if line.get("analytic_distribution"):
                vals["analytic_distribution"] = line["analytic_distribution"]
            line_ids.append((0, 0, vals))

        move_vals = {
            "move_type": "entry",
            "journal_id": journal_id,
            "date": date,
            "line_ids": line_ids,
        }
        if ref:
            move_vals["ref"] = ref
        if company_id:
            move_vals["company_id"] = company_id
        try:
            move_id = client.create("account.move", move_vals)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"id": move_id, "model": "account.move", "state": "draft"}

    @mcp.tool()
    def update_journal_entry(move_id: int, values: dict = None,
                             lines: list = None) -> dict:
        """Update a draft journal entry's header and/or replace its lines
        entirely (same line-dict shape as create_journal_entry's `lines`).
        """
        vals = dict(values or {})
        if lines is not None:
            line_ids = [(5, 0, 0)]
            for line in lines:
                line_vals = {
                    "account_id": line["account_id"],
                    "debit": line.get("debit", 0.0),
                    "credit": line.get("credit", 0.0),
                }
                if line.get("name"):
                    line_vals["name"] = line["name"]
                if line.get("partner_id"):
                    line_vals["partner_id"] = line["partner_id"]
                if line.get("analytic_distribution"):
                    line_vals["analytic_distribution"] = line["analytic_distribution"]
                line_ids.append((0, 0, line_vals))
            vals["line_ids"] = line_ids
        try:
            client.write("account.move", [move_id], vals)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": move_id}

    @mcp.tool()
    def post_journal_entry(move_id: int) -> dict:
        """Post a draft journal entry. Same irreversibility caveat as
        post_invoice -- correct a posted entry with a reversal, not a write.
        """
        if not config.allow_post:
            return {"error": (
                "Posting is disabled on this server "
                "(ODOO_MCP_ALLOW_POST is not true).")}
        try:
            client.call_method("account.move", "action_post", [move_id])
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": move_id, "state": "posted"}

    @mcp.tool()
    def reverse_journal_entry(move_id: int, date: str = None,
                              reason: str = None) -> dict:
        """Create and post a reversal of an already-posted move -- the
        correct way to undo a posted entry (never edit or delete a posted
        move directly)."""
        if not config.allow_post:
            return {"error": (
                "Posting is disabled on this server "
                "(ODOO_MCP_ALLOW_POST is not true), so a reversal (which "
                "posts immediately) cannot be created either.")}
        kwargs = {}
        if date:
            kwargs["date"] = date
        if reason:
            kwargs["reason"] = reason
        try:
            result = client.call_method(
                "account.move", "_reverse_moves", [move_id], **kwargs)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "result": result}

    @mcp.tool()
    def search_journal_entries(domain: list = None, limit: int = 80) -> dict:
        """Search journal entries/invoices/bills of any move_type. Example
        domain: [["move_type", "=", "entry"], ["date", ">=", "2026-01-01"]].
        """
        try:
            records = client.search_read(
                "account.move", domain=domain or [], fields=_MOVE_FIELDS,
                limit=limit, order="date desc, id desc")
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}

    # ── Payments & reconciliation ────────────────────────────────────────
    @mcp.tool()
    def register_payment(move_id: int, journal_id: int, amount: float = None,
                         payment_date: str = None,
                         payment_method_line_id: int = None) -> dict:
        """Register a payment against a posted invoice/bill via Odoo's
        standard account.payment.register wizard model (keeps reconciliation
        correct -- never write account.payment directly)."""
        if not config.allow_post:
            return {"error": (
                "Posting/payments are disabled on this server "
                "(ODOO_MCP_ALLOW_POST is not true).")}
        ctx = {"active_model": "account.move", "active_ids": [move_id]}
        vals = {}
        if amount is not None:
            vals["amount"] = amount
        if payment_date:
            vals["payment_date"] = payment_date
        if payment_method_line_id:
            vals["payment_method_line_id"] = payment_method_line_id
        vals["journal_id"] = journal_id
        try:
            wizard_id = client.execute(
                "account.payment.register", "create", [vals],
                context=ctx)
            wizard_id = wizard_id[0] if isinstance(wizard_id, list) else wizard_id
            result = client.call_method(
                "account.payment.register", "action_create_payments",
                [wizard_id], context=ctx)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "result": result}

    @mcp.tool()
    def reconcile_lines(line_ids: list) -> dict:
        """Reconcile a set of account.move.line ids against each other
        (e.g. a payment line against an invoice line). All lines must
        share the same partner and a reconcilable account."""
        if not config.allow_reconcile:
            return {"error": (
                "Reconciliation is disabled on this server "
                "(ODOO_MCP_ALLOW_RECONCILE is not true).")}
        try:
            result = client.call_method(
                "account.move.line", "reconcile", line_ids)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "result": result}

    @mcp.tool()
    def search_unreconciled_lines(partner_id: int = None,
                                  account_id: int = None,
                                  limit: int = 80) -> dict:
        """Find open (unreconciled) receivable/payable move lines, e.g. to
        match a payment to its invoice."""
        domain = [["reconciled", "=", False], ["account_id.reconcile", "=", True]]
        if partner_id:
            domain.append(["partner_id", "=", partner_id])
        if account_id:
            domain.append(["account_id", "=", account_id])
        try:
            records = client.search_read(
                "account.move.line", domain=domain,
                fields=["id", "move_id", "partner_id", "account_id", "date",
                        "debit", "credit", "balance", "amount_residual"],
                limit=limit, order="date")
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}
