"""BOQ / Project Budget tools, tailored to the `project_budget_boq_sunderland`
Odoo addon (project.budget / project.budget.line) if your instance has it
installed. On an instance without that module, these tools will simply
return an Odoo "model not found" error -- use the generic.py tools against
whatever budgeting model your instance actually has instead.

Core formulas (read-only here; never recomputed client-side, always read
straight from Odoo so they can never drift from the server's own logic):
  Auto ETC  = max(planned_total_cost - actual_cost, 0)
  Effective ETC = manual_etc if etc_mode == 'manual' else Auto ETC
  EAC (forecast_cost_at_completion) = actual_cost + Effective ETC
"""
from ..client import OdooClient, OdooError
from ..config import OdooConfig

_BUDGET_FIELDS = [
    "id", "title", "project_id", "state", "contract_value_original",
    "analytic_account_id", "partner_id", "company_id",
]
# auto_etc / effective_etc / forecast_cost_at_completion are non-stored
# computed Monetary fields -- read() still returns them fine.
_LINE_FIELDS = [
    "id", "name", "boq_code", "budget_id", "section_id", "cost_category_id",
    "category_type", "task_id", "work_package_id", "product_id",
    "uom_id", "planned_qty", "planned_unit_cost", "planned_total_cost",
    "is_lump_sum", "actual_qty", "actual_cost", "etc_mode", "manual_etc",
    "auto_etc", "effective_etc", "forecast_cost_at_completion",
    "available_budget", "commitment_variance", "budget_state",
]


def register(mcp, client: OdooClient, config: OdooConfig) -> None:

    @mcp.tool()
    def list_budgets(project_id: int = None, state: str = None,
                     limit: int = 80) -> dict:
        """List project budgets, optionally filtered by project and/or
        state (e.g. "draft", "submitted", "approved", "active")."""
        domain = []
        if project_id:
            domain.append(["project_id", "=", project_id])
        if state:
            domain.append(["state", "=", state])
        try:
            records = client.search_read(
                "project.budget", domain=domain, fields=_BUDGET_FIELDS,
                limit=limit)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}

    @mcp.tool()
    def get_budget(budget_id: int) -> dict:
        """Full detail of one budget, including every BOQ line with its
        planned/actual/ETC/EAC figures -- read directly from Odoo, never
        recomputed here."""
        try:
            budget = client.read("project.budget", [budget_id],
                                 fields=_BUDGET_FIELDS)
            if not budget:
                return {"error": f"project.budget {budget_id} not found"}
            budget = budget[0]
            lines = client.search_read(
                "project.budget.line", domain=[["budget_id", "=", budget_id]],
                fields=_LINE_FIELDS, order="section_id, boq_code")
        except OdooError as exc:
            return {"error": str(exc)}
        budget["lines"] = lines
        return budget

    @mcp.tool()
    def create_budget_line(budget_id: int, name: str, section_id: int,
                           cost_category_id: int, boq_code: str = None,
                           uom_id: int = None, product_id: int = None,
                           task_id: int = None, work_package_id: int = None,
                           planned_qty: float = None,
                           planned_unit_cost: float = None,
                           is_lump_sum: bool = False,
                           planned_total_cost: float = None,
                           analytic_account_id: int = None) -> dict:
        """Add a new BOQ line to a budget. Either give planned_qty +
        planned_unit_cost, or set is_lump_sum=True with planned_total_cost.
        """
        vals = {
            "budget_id": budget_id, "name": name, "section_id": section_id,
            "cost_category_id": cost_category_id,
        }
        for key, val in (
            ("boq_code", boq_code), ("uom_id", uom_id),
            ("product_id", product_id), ("task_id", task_id),
            ("work_package_id", work_package_id),
            ("analytic_account_id", analytic_account_id),
        ):
            if val is not None:
                vals[key] = val
        if is_lump_sum:
            vals["is_lump_sum"] = True
            vals["planned_total_cost"] = planned_total_cost or 0.0
        else:
            vals["planned_qty"] = planned_qty or 0.0
            vals["planned_unit_cost"] = planned_unit_cost or 0.0
        try:
            line_id = client.create("project.budget.line", vals)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"id": line_id, "model": "project.budget.line"}

    @mcp.tool()
    def update_budget_line(line_id: int, values: dict) -> dict:
        """Update any field(s) on a BOQ line: planned_qty, planned_unit_cost,
        planned_total_cost, etc_mode ("auto"/"manual"), manual_etc, name,
        section_id, cost_category_id, task_id, work_package_id, etc.

        Never write "auto_etc", "effective_etc" or
        "forecast_cost_at_completion" directly -- they are always computed
        by Odoo from planned/actual/manual_etc; Odoo will simply ignore or
        reject an attempt to write them. To move the forecast, set
        etc_mode="manual" and manual_etc=<value> instead."""
        try:
            client.write("project.budget.line", [line_id], values)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": line_id}

    @mcp.tool()
    def submit_budget(budget_id: int) -> dict:
        """Move a draft budget to Submitted (action_submit)."""
        try:
            client.call_method("project.budget", "action_submit", [budget_id])
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": budget_id}

    @mcp.tool()
    def approve_budget(budget_id: int) -> dict:
        """Approve a submitted budget (action_approve)."""
        try:
            client.call_method("project.budget", "action_approve", [budget_id])
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": budget_id}

    @mcp.tool()
    def activate_budget(budget_id: int) -> dict:
        """Activate an approved budget so it can receive real transactions
        (action_activate)."""
        try:
            client.call_method("project.budget", "action_activate", [budget_id])
        except OdooError as exc:
            return {"error": str(exc)}
        return {"ok": True, "id": budget_id}

    @mcp.tool()
    def budget_vs_actual(budget_id: int) -> dict:
        """Budget-vs-actual summary for one budget: per line and totals for
        planned cost, actual cost, effective ETC, forecast EAC and
        available budget -- all read straight from Odoo's own computed
        fields, never recalculated here."""
        try:
            lines = client.search_read(
                "project.budget.line", domain=[["budget_id", "=", budget_id]],
                fields=_LINE_FIELDS, order="section_id, boq_code")
        except OdooError as exc:
            return {"error": str(exc)}
        totals = {
            "planned_total_cost": 0.0, "actual_cost": 0.0,
            "effective_etc": 0.0, "forecast_cost_at_completion": 0.0,
            "available_budget": 0.0,
        }
        for line in lines:
            for key in totals:
                totals[key] += line.get(key) or 0.0
        return {"budget_id": budget_id, "lines": lines,
                "totals": {k: round(v, 2) for k, v in totals.items()}}

    @mcp.tool()
    def search_budget_lines(domain: list = None, limit: int = 80) -> dict:
        """Search BOQ lines across any budget/project. Example domain:
        [["category_type", "=", "labor"], ["budget_state", "=", "active"]].
        """
        try:
            records = client.search_read(
                "project.budget.line", domain=domain or [],
                fields=_LINE_FIELDS, limit=limit)
        except OdooError as exc:
            return {"error": str(exc)}
        return {"count": len(records), "records": records}
