"""Thin wrapper around Odoo's standard external API (XML-RPC).

No Odoo module/addon is required on the target instance -- this talks to
the same /xmlrpc/2/common and /xmlrpc/2/object endpoints any external
integration uses, authenticated as a normal Odoo user (identified by an
API key, never a password). Every Odoo access-right, record rule and
field-level security restriction that applies to that user still applies
here: this client has exactly the permissions the Odoo user account has,
nothing more.
"""
import logging
import xmlrpc.client
from typing import Any, Optional

from .config import OdooConfig

_logger = logging.getLogger("odoo_mcp.client")


class OdooError(RuntimeError):
    """Raised when Odoo itself rejects a call (validation error, access
    error, missing record, etc). Wraps the underlying XML-RPC fault so the
    calling tool can return a clean message instead of a raw traceback."""


class OdooClient:
    def __init__(self, config: OdooConfig):
        self.config = config
        self._common = xmlrpc.client.ServerProxy(
            f"{config.url}/xmlrpc/2/common", allow_none=True)
        self._models = xmlrpc.client.ServerProxy(
            f"{config.url}/xmlrpc/2/object", allow_none=True)
        self._uid: Optional[int] = None

    def authenticate(self) -> int:
        if self._uid is None:
            try:
                uid = self._common.authenticate(
                    self.config.db, self.config.username,
                    self.config.api_key, {})
            except xmlrpc.client.Fault as exc:
                raise OdooError(f"Odoo authentication error: {exc.faultString}") from exc
            except (OSError, xmlrpc.client.ProtocolError) as exc:
                raise OdooError(
                    f"Could not reach Odoo at {self.config.url}: {exc}") from exc
            if not uid:
                raise OdooError(
                    "Odoo rejected the credentials (bad db/username/api key), "
                    "or the account has no access.")
            self._uid = uid
        return self._uid

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        uid = self.authenticate()
        try:
            return self._models.execute_kw(
                self.config.db, uid, self.config.api_key,
                model, method, list(args), kwargs)
        except xmlrpc.client.Fault as exc:
            raise OdooError(
                f"{model}.{method} failed: {exc.faultString}") from exc
        except (OSError, xmlrpc.client.ProtocolError) as exc:
            raise OdooError(f"Could not reach Odoo: {exc}") from exc

    # ── Generic CRUD (works against ANY model the Odoo user can access) ────
    def search(self, model: str, domain=None, limit=None, offset=0, order=None):
        kwargs = {"offset": offset}
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search", domain or [], **kwargs)

    def search_count(self, model: str, domain=None) -> int:
        return self.execute(model, "search_count", domain or [])

    def search_read(self, model: str, domain=None, fields=None,
                    limit=None, offset=0, order=None):
        kwargs = {"offset": offset}
        if fields:
            kwargs["fields"] = fields
        if limit is not None:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain or [], **kwargs)

    def read(self, model: str, ids, fields=None):
        kwargs = {"fields": fields} if fields else {}
        return self.execute(model, "read", ids, **kwargs)

    def create(self, model: str, values: dict) -> int:
        result = self.execute(model, "create", [values])
        return result[0] if isinstance(result, list) else result

    def write(self, model: str, ids, values: dict) -> bool:
        return self.execute(model, "write", ids, values)

    def unlink(self, model: str, ids) -> bool:
        return self.execute(model, "unlink", ids)

    def call_method(self, model: str, method: str, ids, *args, **kwargs):
        return self.execute(model, method, ids, *args, **kwargs)

    def fields_get(self, model: str, attributes=None) -> dict:
        return self.execute(
            model, "fields_get",
            attributes=attributes or [
                "string", "type", "required", "readonly", "relation",
                "selection", "help"])
