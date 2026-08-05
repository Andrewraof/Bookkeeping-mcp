"""Unit tests for OdooClient using a mocked xmlrpc.client.ServerProxy --
there is no real Odoo server available in this environment, so these verify
the request-shaping logic (auth caching, args/kwargs wrapping, error
mapping) rather than a live round trip.
"""
import xmlrpc.client
from unittest.mock import MagicMock, patch

import pytest

from odoo_mcp.client import OdooClient, OdooError
from odoo_mcp.config import OdooConfig

CONFIG = OdooConfig(url="https://example.odoo.com", db="test-db",
                    username="bot@example.com", api_key="secret-key")


def _client_with_mocks():
    with patch("odoo_mcp.client.xmlrpc.client.ServerProxy") as proxy_cls:
        common = MagicMock()
        models = MagicMock()
        proxy_cls.side_effect = [common, models]
        client = OdooClient(CONFIG)
    return client, common, models


def test_authenticate_caches_uid():
    client, common, _ = _client_with_mocks()
    common.authenticate.return_value = 7
    uid1 = client.authenticate()
    uid2 = client.authenticate()
    assert uid1 == 7 and uid2 == 7
    common.authenticate.assert_called_once()  # cached, not re-authenticated


def test_authenticate_rejects_bad_credentials():
    client, common, _ = _client_with_mocks()
    common.authenticate.return_value = False
    with pytest.raises(OdooError):
        client.authenticate()


def test_execute_wraps_xmlrpc_fault():
    client, common, models = _client_with_mocks()
    common.authenticate.return_value = 7
    models.execute_kw.side_effect = xmlrpc.client.Fault(1, "Access Denied")
    with pytest.raises(OdooError, match="Access Denied"):
        client.execute("res.partner", "read", [1])


def test_create_returns_single_id_not_a_list():
    client, common, models = _client_with_mocks()
    common.authenticate.return_value = 7
    models.execute_kw.return_value = [42]
    new_id = client.create("res.partner", {"name": "Acme"})
    assert new_id == 42
    # exactly one execute_kw call -- create() must never call execute twice
    assert models.execute_kw.call_count == 1
    call_args = models.execute_kw.call_args[0]
    # (db, uid, key, model, method, args, kwargs)
    assert call_args[3] == "res.partner"
    assert call_args[4] == "create"
    # execute_kw's "args" is [vals_list]; vals_list is [{"name": "Acme"}].
    assert call_args[5] == [[{"name": "Acme"}]]


def test_search_read_passes_domain_fields_limit():
    client, common, models = _client_with_mocks()
    common.authenticate.return_value = 7
    models.execute_kw.return_value = [{"id": 1, "name": "X"}]
    result = client.search_read(
        "account.move", domain=[["state", "=", "draft"]],
        fields=["id", "name"], limit=10)
    assert result == [{"id": 1, "name": "X"}]
    positional = models.execute_kw.call_args[0]
    assert positional[4] == "search_read"
    assert positional[5] == [[["state", "=", "draft"]]]
    kwargs = positional[6]
    assert kwargs["fields"] == ["id", "name"]
    assert kwargs["limit"] == 10


def test_write_and_unlink_call_shape():
    client, common, models = _client_with_mocks()
    common.authenticate.return_value = 7
    models.execute_kw.return_value = True
    client.write("res.partner", [1, 2], {"name": "New"})
    positional = models.execute_kw.call_args[0]
    assert positional[4] == "write"
    assert positional[5] == [[1, 2], {"name": "New"}]

    client.unlink("res.partner", [1])
    positional = models.execute_kw.call_args[0]
    assert positional[4] == "unlink"
    assert positional[5] == [[1]]


def test_network_error_wrapped_as_odoo_error():
    client, common, models = _client_with_mocks()
    common.authenticate.return_value = 7
    models.execute_kw.side_effect = OSError("connection refused")
    with pytest.raises(OdooError, match="Could not reach Odoo"):
        client.execute("res.partner", "read", [1])
