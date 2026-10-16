"""Shared pytest setup for the backend tests (plan §5.9).

This module does two jobs, and only these two.

1. It puts `backend/` on sys.path, so every test file can `from app.xxx import yyy`
   without its own shim. It runs before anything else in this module.

2. It guards every test marked `integration`. Before an integration test body runs,
   the guard checks the test-environment configuration:
   - APP_ENV is set to `test`. A dev run stops with a clear error.
   - settings.MYSQL_DATABASE and settings.NEO4J_DATABASE end with `_test`.
   - settings.GRAPH_GROUP_ID starts with `test_`.
   A failed check calls pytest.fail, so the run stops loudly. A configuration
   error is never reported as skipped.

Boundary: this module does NOT check whether a live service is running. A test
that needs Neo4j or MySQL checks that itself. It tries to connect, and on a
connection error it calls pytest.skip("not verified: <service> not running").
The report counts that skip as "not verified", never as passed. The guard here
only guarantees the test stack configuration is correct before that check runs.

Unit tests (no marker) are not affected. The guard returns before it imports
app.config, so unit tests run with no .env or .env.test present.
"""

import os
import sys
from pathlib import Path

import pytest

# backend/ is not an installed package (package = false in pyproject.toml), and
# pytest does not put it on sys.path. This line must run before any `app` import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _integration_test_environment_guard(request: pytest.FixtureRequest) -> None:
    """Refuse to run an integration test unless the test stack settings are in place."""
    if request.node.get_closest_marker("integration") is None:
        return

    app_env = os.environ.get("APP_ENV")
    if app_env != "test":
        pytest.fail(
            f"Integration test refused: APP_ENV is {app_env!r}, but it must be 'test'. "
            "Export APP_ENV=test so the run reads .env.test. Integration tests never "
            "run against dev settings.",
            pytrace=False,
        )

    # Imported here, not at module top, so unit tests never load app.config.
    try:
        from app.config import settings
    except Exception as exc:  # missing .env.test, or a required field missing
        pytest.fail(
            f"Integration test refused: the test settings could not be loaded: {exc}",
            pytrace=False,
        )

    problems: list[str] = []
    if not settings.MYSQL_DATABASE.endswith("_test"):
        problems.append(
            f"MYSQL_DATABASE is {settings.MYSQL_DATABASE!r}, which does not end in '_test'"
        )
    if not settings.NEO4J_DATABASE.endswith("_test"):
        problems.append(
            f"NEO4J_DATABASE is {settings.NEO4J_DATABASE!r}, which does not end in '_test'"
        )
    if not settings.GRAPH_GROUP_ID.startswith("test_"):
        problems.append(
            f"GRAPH_GROUP_ID is {settings.GRAPH_GROUP_ID!r}, which does not start with 'test_'"
        )
    if problems:
        pytest.fail(
            "Integration test refused: the test settings point at non-test data. "
            + "; ".join(problems)
            + ". Fix .env.test before running integration tests.",
            pytrace=False,
        )
