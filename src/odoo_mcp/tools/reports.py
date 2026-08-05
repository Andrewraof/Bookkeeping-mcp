"""Financial reports computed directly from posted account.move.line data.

These do NOT call Odoo's built-in QWeb accounting report engine (that
engine is wired to the web client, not reliably reachable over the plain
external API across Odoo versions). Instead they aggregate posted journal
items the same way those reports fundamentally do: group by account, sum
debit/credit. Figures are accurate; layout/grouping conventions may differ
slightly from Odoo's own PDF report.
"""
from collections import defaultdict

from ..client import OdooClient, OdooError
from ..config import OdooConfig

_INCOME_TYPES = ("income", "income_other")
_EXPENSE_TYPES = ("expense", "expense_depreciation", "expense_direct_cost")
_ASSET_TYPES = ("asset_receivable", "asset_cash", "asset_current",
               "asset_non_current", "asset_prepayments", "asset_fixed")
_LIABILITY_TYPES = ("liability_payable", "liability_credit_card",
                    "liability_current", "liability_non_current")
_EQUITY_TYPES = ("equity", "equity_unaffected")


def _account_type_map(client: OdooClient, account_ids) -> dict:
    accounts = client.search_read(
        "account.account", domain=[["id", "in", list(set(account_ids))]],
        fields=["id", "code", "name", "account_type"])
    return {a["id"]: a for a in accounts}


def register(mcp, client: OdooClient, config: OdooConfig) -> None:

    @mcp.tool()
    def profit_and_loss(date_from: str, date_to: str,
                        company_id: int = None) -> dict:
        """Profit & Loss (income statement) for a date range: income and
        expense accounts, from posted journal items only."""
        domain = [
            ["move_id.state", "=", "posted"],
            ["date", ">=", date_from], ["date", "<=", date_to],
            ["account_id.account_type", "in",
             list(_INCOME_TYPES + _EXPENSE_TYPES)],
        ]
        if company_id:
            domain.append(["company_id", "=", company_id])
        try:
            lines = client.search_read(
                "account.move.line", domain=domain,
                fields=["account_id", "debit", "credit", "balance"],
                limit=0)
        except OdooError as exc:
            return {"error": str(exc)}

        totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
        for line in lines:
            acc = line["account_id"]
            key = acc[0] if isinstance(acc, list) else acc
            totals[key]["debit"] += line["debit"]
            totals[key]["credit"] += line["credit"]
            totals[key]["name"] = acc[1] if isinstance(acc, list) else str(acc)

        acc_types = _account_type_map(client, totals.keys())
        income_lines, expense_lines = [], []
        total_income = total_expense = 0.0
        for account_id, agg in totals.items():
            acc_type = acc_types.get(account_id, {}).get("account_type")
            # Income is naturally a credit balance -> report as positive.
            amount = agg["credit"] - agg["debit"]
            row = {"account_id": account_id, "account": agg["name"],
                  "amount": round(amount, 2)}
            if acc_type in _INCOME_TYPES:
                income_lines.append(row)
                total_income += amount
            elif acc_type in _EXPENSE_TYPES:
                row["amount"] = round(-amount, 2)  # expense: debit balance -> positive
                expense_lines.append(row)
                total_expense += row["amount"]

        return {
            "date_from": date_from, "date_to": date_to,
            "income": sorted(income_lines, key=lambda r: r["account"]),
            "expense": sorted(expense_lines, key=lambda r: r["account"]),
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "net_profit": round(total_income - total_expense, 2),
        }

    @mcp.tool()
    def balance_sheet(as_of_date: str, company_id: int = None) -> dict:
        """Balance Sheet (assets / liabilities / equity) as of a date, from
        posted journal items only, computed as cumulative balances from
        the earliest entry up to as_of_date."""
        domain = [
            ["move_id.state", "=", "posted"], ["date", "<=", as_of_date],
            ["account_id.account_type", "in",
             list(_ASSET_TYPES + _LIABILITY_TYPES + _EQUITY_TYPES)],
        ]
        if company_id:
            domain.append(["company_id", "=", company_id])
        try:
            lines = client.search_read(
                "account.move.line", domain=domain,
                fields=["account_id", "debit", "credit"], limit=0)
        except OdooError as exc:
            return {"error": str(exc)}

        totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
        for line in lines:
            acc = line["account_id"]
            key = acc[0] if isinstance(acc, list) else acc
            totals[key]["debit"] += line["debit"]
            totals[key]["credit"] += line["credit"]
            totals[key]["name"] = acc[1] if isinstance(acc, list) else str(acc)

        acc_types = _account_type_map(client, totals.keys())
        assets, liabilities, equity = [], [], []
        total_assets = total_liabilities = total_equity = 0.0
        for account_id, agg in totals.items():
            acc_type = acc_types.get(account_id, {}).get("account_type")
            row = {"account_id": account_id, "account": agg["name"]}
            if acc_type in _ASSET_TYPES:
                row["amount"] = round(agg["debit"] - agg["credit"], 2)
                assets.append(row)
                total_assets += row["amount"]
            elif acc_type in _LIABILITY_TYPES:
                row["amount"] = round(agg["credit"] - agg["debit"], 2)
                liabilities.append(row)
                total_liabilities += row["amount"]
            elif acc_type in _EQUITY_TYPES:
                row["amount"] = round(agg["credit"] - agg["debit"], 2)
                equity.append(row)
                total_equity += row["amount"]

        return {
            "as_of_date": as_of_date,
            "assets": sorted(assets, key=lambda r: r["account"]),
            "liabilities": sorted(liabilities, key=lambda r: r["account"]),
            "equity": sorted(equity, key=lambda r: r["account"]),
            "total_assets": round(total_assets, 2),
            "total_liabilities": round(total_liabilities, 2),
            "total_equity": round(total_equity, 2),
            "balances": round(
                total_assets - total_liabilities - total_equity, 2),
        }

    @mcp.tool()
    def trial_balance(date_from: str, date_to: str,
                      company_id: int = None) -> dict:
        """Trial balance: opening + period debit/credit + closing balance
        per account, for a period."""
        domain = [["move_id.state", "=", "posted"],
                 ["date", ">=", date_from], ["date", "<=", date_to]]
        if company_id:
            domain.append(["company_id", "=", company_id])
        try:
            lines = client.search_read(
                "account.move.line", domain=domain,
                fields=["account_id", "debit", "credit"], limit=0)
        except OdooError as exc:
            return {"error": str(exc)}
        totals = defaultdict(lambda: {"debit": 0.0, "credit": 0.0})
        for line in lines:
            acc = line["account_id"]
            key = acc[0] if isinstance(acc, list) else acc
            totals[key]["debit"] += line["debit"]
            totals[key]["credit"] += line["credit"]
            totals[key]["name"] = acc[1] if isinstance(acc, list) else str(acc)
        rows = [
            {"account_id": aid, "account": agg["name"],
            "debit": round(agg["debit"], 2), "credit": round(agg["credit"], 2),
            "balance": round(agg["debit"] - agg["credit"], 2)}
            for aid, agg in totals.items()
        ]
        return {
            "date_from": date_from, "date_to": date_to,
            "accounts": sorted(rows, key=lambda r: r["account"]),
            "total_debit": round(sum(r["debit"] for r in rows), 2),
            "total_credit": round(sum(r["credit"] for r in rows), 2),
        }

    @mcp.tool()
    def general_ledger(account_id: int, date_from: str, date_to: str) -> dict:
        """All posted journal items on one account for a period, in date
        order, with a running balance."""
        try:
            lines = client.search_read(
                "account.move.line",
                domain=[["account_id", "=", account_id],
                       ["move_id.state", "=", "posted"],
                       ["date", ">=", date_from], ["date", "<=", date_to]],
                fields=["date", "move_id", "name", "partner_id", "debit",
                       "credit"],
                order="date, id")
        except OdooError as exc:
            return {"error": str(exc)}
        running = 0.0
        for line in lines:
            running += line["debit"] - line["credit"]
            line["running_balance"] = round(running, 2)
        return {"account_id": account_id, "date_from": date_from,
               "date_to": date_to, "lines": lines,
               "closing_balance": round(running, 2)}

    @mcp.tool()
    def aged_receivable(as_of_date: str, partner_id: int = None) -> dict:
        """Aged receivable: open customer invoice balances, bucketed by
        days overdue as of a date."""
        return _aged_report(client, as_of_date, partner_id,
                            move_types=["out_invoice", "out_refund"])

    @mcp.tool()
    def aged_payable(as_of_date: str, partner_id: int = None) -> dict:
        """Aged payable: open vendor bill balances, bucketed by days
        overdue as of a date."""
        return _aged_report(client, as_of_date, partner_id,
                            move_types=["in_invoice", "in_refund"])


def _aged_report(client: OdooClient, as_of_date: str, partner_id, move_types):
    from datetime import date as _date
    domain = [
        ["move_id.state", "=", "posted"],
        ["move_id.move_type", "in", move_types],
        ["reconciled", "=", False],
        ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]],
    ]
    if partner_id:
        domain.append(["partner_id", "=", partner_id])
    try:
        lines = client.search_read(
            "account.move.line", domain=domain,
            fields=["move_id", "partner_id", "date_maturity", "date",
                   "amount_residual", "currency_id"], limit=0)
    except OdooError as exc:
        return {"error": str(exc)}

    today = _date.fromisoformat(as_of_date)
    buckets = {"not_due": 0.0, "1_30": 0.0, "31_60": 0.0, "61_90": 0.0,
              "90_plus": 0.0}
    rows = []
    for line in lines:
        residual = line["amount_residual"]
        if not residual:
            continue
        due = line.get("date_maturity") or line.get("date")
        due_date = _date.fromisoformat(due) if due else today
        days_overdue = (today - due_date).days
        if days_overdue <= 0:
            bucket = "not_due"
        elif days_overdue <= 30:
            bucket = "1_30"
        elif days_overdue <= 60:
            bucket = "31_60"
        elif days_overdue <= 90:
            bucket = "61_90"
        else:
            bucket = "90_plus"
        buckets[bucket] += residual
        rows.append({
            "move": line["move_id"], "partner": line["partner_id"],
            "due_date": due, "amount_residual": round(residual, 2),
            "days_overdue": days_overdue, "bucket": bucket,
        })
    return {
        "as_of_date": as_of_date,
        "lines": rows,
        "buckets": {k: round(v, 2) for k, v in buckets.items()},
        "total": round(sum(buckets.values()), 2),
    }
