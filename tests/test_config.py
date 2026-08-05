import pytest

from odoo_mcp.config import OdooConfig, OdooConfigError

REQUIRED = {
    "ODOO_URL": "https://example.odoo.com",
    "ODOO_DB": "test-db",
    "ODOO_USERNAME": "bot@example.com",
    "ODOO_API_KEY": "secret-key",
}


def _clear_env(monkeypatch):
    for key in list(REQUIRED) + [
        "ODOO_MCP_ALLOW_UNLINK", "ODOO_MCP_ALLOW_POST",
        "ODOO_MCP_ALLOW_RECONCILE", "ODOO_MCP_CONFIRM_DESTRUCTIVE",
    ]:
        monkeypatch.delenv(key, raising=False)


def test_missing_vars_raise(monkeypatch):
    _clear_env(monkeypatch)
    with pytest.raises(OdooConfigError):
        OdooConfig.from_env()


def test_valid_env_builds_config(monkeypatch):
    _clear_env(monkeypatch)
    for key, val in REQUIRED.items():
        monkeypatch.setenv(key, val)
    config = OdooConfig.from_env()
    assert config.url == REQUIRED["ODOO_URL"]
    assert config.db == REQUIRED["ODOO_DB"]
    # Safe defaults: unlink off, post/reconcile on.
    assert config.allow_unlink is False
    assert config.allow_post is True
    assert config.allow_reconcile is True


def test_trailing_slash_stripped(monkeypatch):
    _clear_env(monkeypatch)
    for key, val in REQUIRED.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setenv("ODOO_URL", "https://example.odoo.com/")
    config = OdooConfig.from_env()
    assert config.url == "https://example.odoo.com"


def test_url_must_have_scheme(monkeypatch):
    _clear_env(monkeypatch)
    for key, val in REQUIRED.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setenv("ODOO_URL", "example.odoo.com")
    with pytest.raises(OdooConfigError):
        OdooConfig.from_env()


def test_safety_valves_are_configurable(monkeypatch):
    _clear_env(monkeypatch)
    for key, val in REQUIRED.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setenv("ODOO_MCP_ALLOW_UNLINK", "true")
    monkeypatch.setenv("ODOO_MCP_ALLOW_POST", "false")
    config = OdooConfig.from_env()
    assert config.allow_unlink is True
    assert config.allow_post is False
