"""Offline API binding protections."""
import pytest
from app.services.rick_security_network import is_loopback_binding, safe_api_bind_host


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "[::1]", "localhost"])
def test_loopback_detected(host):
    assert is_loopback_binding(host)
    assert safe_api_bind_host(host, "") == host


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.15", "example.net"])
def test_no_key_forces_local_only(host):
    assert not is_loopback_binding(host)
    assert safe_api_bind_host(host, "") == "127.0.0.1"


def test_authenticated_remote_bind_explicitly_allowed():
    assert safe_api_bind_host("0.0.0.0", "configured") == "0.0.0.0"


@pytest.mark.parametrize("key", [None, 3, ["invalid"]])
def test_invalid_key_configuration_rejected(key):
    with pytest.raises(ValueError, match="authentication"):
        safe_api_bind_host("0.0.0.0", key)
