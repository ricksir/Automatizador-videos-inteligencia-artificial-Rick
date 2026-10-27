"""No-network regression for the public-output secret guard."""
from __future__ import annotations

from scripts import rick_security_guard as guard


def test_blocks_common_secret_filenames():
    for filename in (
        "config.toml", "nested/config.toml.bak", "dir/.env",
        "dir/.env.production", "nested/secrets.toml",
        "keys/id_ed25519", "private/client.p12",
        "storage/tasks/result.json", "logs/app.log",
        "keys/service_account.json",
    ):
        assert guard.risky_path(filename), filename


def test_allows_public_templates_and_regular_code():
    for filename in (
        "config.example.toml", ".env.example", "pyproject.toml",
        ".github/workflows/ci.yml", "docs/rick-guide.md",
        "app/services/task.py", "test/services/test_config.py",
        "webui/.streamlit/config.toml",
    ):
        assert not guard.risky_path(filename), filename


def test_redacts_secret_values_and_returns_only_categories():
    example = b"prefix " + b"ghp_" + b"x" * 36 + b" suffix"
    categories = guard.secret_categories(example)
    assert "github_token" in categories
    assert all("ghp_" not in item for item in categories)


def test_does_not_warn_on_generic_label_without_secret():
    sample = b'api_key = "YOUR_API_KEY"\npassword = "placeholder"'
    assert guard.secret_categories(sample) == []


def test_private_key_header_detected():
    header = b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----"
    assert "private_key" in guard.secret_categories(header)
