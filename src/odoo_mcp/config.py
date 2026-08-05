"""Connection configuration for the target Odoo instance.

Every value comes from the environment -- nothing is ever hardcoded here.
See .env.example for the variables this reads.
"""
import os
from dataclasses import dataclass


class OdooConfigError(RuntimeError):
    """Raised when required Odoo connection environment variables are
    missing or malformed."""


@dataclass(frozen=True)
class OdooConfig:
    url: str
    db: str
    username: str
    api_key: str
    # Safety valves -- all default to the safest (most restrictive) setting.
    # See README "Safety valves" for what each one gates.
    allow_unlink: bool = False
    allow_post: bool = True
    allow_reconcile: bool = True
    confirm_destructive: bool = False

    @classmethod
    def from_env(cls) -> "OdooConfig":
        url = os.environ.get("ODOO_URL", "").strip()
        db = os.environ.get("ODOO_DB", "").strip()
        username = os.environ.get("ODOO_USERNAME", "").strip()
        api_key = os.environ.get("ODOO_API_KEY", "").strip()

        missing = [
            name for name, value in (
                ("ODOO_URL", url), ("ODOO_DB", db),
                ("ODOO_USERNAME", username), ("ODOO_API_KEY", api_key),
            ) if not value
        ]
        if missing:
            raise OdooConfigError(
                "Missing required environment variable(s): %s. "
                "Copy .env.example to .env and fill in your real Odoo "
                "connection details -- see README.md." % ", ".join(missing))

        if not (url.startswith("http://") or url.startswith("https://")):
            raise OdooConfigError(
                "ODOO_URL must start with http:// or https:// (got: %r)"
                % url)

        def _bool_env(name: str, default: bool) -> bool:
            raw = os.environ.get(name)
            if raw is None:
                return default
            return raw.strip().lower() in ("1", "true", "yes", "on")

        return cls(
            url=url.rstrip("/"),
            db=db,
            username=username,
            api_key=api_key,
            allow_unlink=_bool_env("ODOO_MCP_ALLOW_UNLINK", False),
            allow_post=_bool_env("ODOO_MCP_ALLOW_POST", True),
            allow_reconcile=_bool_env("ODOO_MCP_ALLOW_RECONCILE", True),
            confirm_destructive=_bool_env(
                "ODOO_MCP_CONFIRM_DESTRUCTIVE", False),
        )
