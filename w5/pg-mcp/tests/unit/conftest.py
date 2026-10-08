"""Unit test configuration.

Isolates unit tests from the developer's local ``.env`` file: unit tests must
exercise config defaults, not whatever happens to be configured on this
machine. Real environment variables still take precedence, as in production.
"""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run unit tests from an empty directory so no local .env is discovered."""
    monkeypatch.chdir(tmp_path)
