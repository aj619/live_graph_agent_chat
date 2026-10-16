"""Tests for the plan §9.3 security headers on API responses (app.security_headers).

The middleware is mounted on a small scratch FastAPI app built inside this file.
The real app.main is never imported, because its lifespan needs live Neo4j and
MySQL. No service is needed, and no .env file is read. security_headers.py has no
dependency on app.config.

Covered:
- A 200 response, a 404 from HTTPException, and a non-JSON body all get both headers.
- An unhandled RuntimeError becomes a 500 with the generic JSON body, no internal
  detail in the body, both headers on the 500, and an ERROR log record whose
  message text does not contain the exception message.
- Ordering with CORSMiddleware added first, as main.py does, leaves the headers in place.

backend/ is on sys.path through tests/conftest.py, so no sys.path shim is needed.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.testclient import TestClient

from app.security_headers import GENERIC_ERROR_DETAIL, SECURITY_HEADERS, SecurityHeadersMiddleware

EXPECTED_NOSNIFF = "nosniff"
EXPECTED_REFERRER = "no-referrer"
BOOM_MESSAGE = "boom"
ALLOWED_ORIGIN = "http://localhost:5173"


def _build_app() -> FastAPI:
    """Build a scratch app with SecurityHeadersMiddleware, mirroring main.py's registration."""
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "fine"}

    @app.get("/missing")
    def missing() -> None:
        raise HTTPException(status_code=404, detail="Nope.")

    @app.get("/explode")
    def explode() -> None:
        raise RuntimeError(BOOM_MESSAGE)

    @app.get("/text")
    def text() -> PlainTextResponse:
        return PlainTextResponse("plain words")

    @app.get("/html")
    def html() -> HTMLResponse:
        return HTMLResponse("<p>markup</p>")

    @app.get("/other")
    def other() -> dict[str, int]:
        return {"n": 1}

    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_build_app())


def test_security_header_constants_have_plan_values() -> None:
    assert SECURITY_HEADERS == {
        "X-Content-Type-Options": EXPECTED_NOSNIFF,
        "Referrer-Policy": EXPECTED_REFERRER,
    }


def test_ok_response_has_nosniff_and_no_referrer_headers(client: TestClient) -> None:
    response = client.get("/ok")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


def test_http_exception_404_keeps_security_headers(client: TestClient) -> None:
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Nope."}
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


def test_unhandled_exception_returns_generic_500_json(client: TestClient) -> None:
    response = client.get("/explode")

    assert response.status_code == 500
    assert response.json() == {"detail": GENERIC_ERROR_DETAIL}
    assert GENERIC_ERROR_DETAIL == "Internal server error."


def test_unhandled_exception_body_leaks_no_internal_detail(client: TestClient) -> None:
    response = client.get("/explode")

    assert BOOM_MESSAGE not in response.text
    assert "RuntimeError" not in response.text


def test_unhandled_exception_500_keeps_security_headers(client: TestClient) -> None:
    response = client.get("/explode")

    assert response.status_code == 500
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


def test_unhandled_exception_logs_error_without_exception_text_in_message(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR, logger="app.security_headers"):
        client.get("/explode")

    records = [r for r in caplog.records if r.name == "app.security_headers"]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.getMessage() == "Unhandled exception in GET /explode"
    assert BOOM_MESSAGE not in record.getMessage()
    # The traceback is kept separately in exc_info, so the logger still has the exception.
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], RuntimeError)


def test_plain_text_response_keeps_security_headers(client: TestClient) -> None:
    response = client.get("/text")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


def test_html_response_keeps_security_headers(client: TestClient) -> None:
    response = client.get("/html")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


@pytest.mark.parametrize("path", ["/ok", "/other", "/text"])
def test_each_route_independently_gets_security_headers(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER


def test_security_headers_survive_cors_middleware_added_first() -> None:
    # main.py adds CORS first, then SecurityHeadersMiddleware, so the headers wrap CORS.
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[ALLOWED_ORIGIN],
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "fine"}

    client = TestClient(app)
    response = client.get("/ok", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["X-Content-Type-Options"] == EXPECTED_NOSNIFF
    assert response.headers["Referrer-Policy"] == EXPECTED_REFERRER
