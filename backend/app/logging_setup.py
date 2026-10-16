"""Structured logging for the backend (plan §6.10, AGENT.md §9).

configure_logging() sets up the root logger so every record is written as one
key=value line (not JSON). A filter replaces every current secret value from
app.config.settings with *** before a record is formatted, so a secret never
reaches the output in the message, an extra field, or a traceback.
"""

import json
import logging
import traceback
from datetime import UTC, datetime
from typing import IO

from app import config

REDACTED = "***"

# Settings fields whose values must never appear in a log line. The values are
# read from config.settings on every call, so the filter always uses the live values.
SECRET_FIELD_NAMES: tuple[str, ...] = (
    "API_TOKEN",
    "MYSQL_PASSWORD",
    "MYSQL_ROOT_PASSWORD",
    "NEO4J_PASSWORD",
    "LLM_API_KEY",
    "EMBEDDING_API_KEY",
    "AGENT_LLM_API_KEY",
    "LANGFUSE_SECRET_KEY",
    "NEXTAUTH_SECRET",
    "SALT",
    "ENCRYPTION_KEY",
    "POSTGRES_PASSWORD",
    "CLICKHOUSE_PASSWORD",
    "REDIS_AUTH",
    "MINIO_ROOT_PASSWORD",
)

HANDLER_NAME = "lgac_structured"

# Attributes that every LogRecord has. Any other attribute came from `extra=`.
_RESERVED_RECORD_KEYS: frozenset[str] = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()
) | {"message", "asctime"}


def current_secret_values() -> list[str]:
    """Return the non-empty secret values now held in settings, longest first."""
    values: set[str] = set()
    for name in SECRET_FIELD_NAMES:
        value = getattr(config.settings, name, None)
        if isinstance(value, str) and value:
            values.add(value)
    # Longest first, so a secret that contains another secret is replaced whole.
    return sorted(values, key=len, reverse=True)


def redact(text: str) -> str:
    """Replace every occurrence of a current secret value in text with ***."""
    for secret in current_secret_values():
        text = text.replace(secret, REDACTED)
    return text


class SecretRedactingFilter(logging.Filter):
    """Redacts secrets in the message, extra fields, traceback, and stack text."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        for key, value in list(vars(record).items()):
            if key not in _RESERVED_RECORD_KEYS:
                setattr(record, key, redact(str(value)))
        exc_info = record.exc_info
        if exc_info is not None and exc_info[1] is not None:
            record.exc_text = redact("".join(traceback.format_exception(exc_info[1])))
        if record.stack_info:
            record.stack_info = redact(record.stack_info)
        return True


def _format_value(value: str) -> str:
    """Return value bare when it is a plain token, otherwise as a JSON string."""
    if value and value.isprintable() and not any(c.isspace() or c in '="' for c in value):
        return value
    return json.dumps(value)


class KeyValueFormatter(logging.Formatter):
    """Formats a record as ts=... level=... logger=... msg=... plus any extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=UTC).isoformat(
            timespec="milliseconds"
        )
        fields: list[tuple[str, str]] = [
            ("ts", timestamp),
            ("level", record.levelname),
            ("logger", record.name),
            ("msg", record.getMessage()),
        ]
        for key, value in vars(record).items():
            if key not in _RESERVED_RECORD_KEYS:
                fields.append((key, str(value)))
        exc_text = record.exc_text
        if not exc_text and record.exc_info:
            exc_text = self.formatException(record.exc_info)
        if exc_text:
            fields.append(("exc", exc_text))
        if record.stack_info:
            fields.append(("stack", record.stack_info))
        line = " ".join(f"{key}={_format_value(value)}" for key, value in fields)
        # Last check on the finished line, so no path can leak a secret.
        return redact(line)


def configure_logging(level: int = logging.INFO, stream: IO[str] | None = None) -> None:
    """Install the structured, redacting handler on the root logger. Safe to call twice."""
    root = logging.getLogger()
    for existing in list(root.handlers):
        if existing.get_name() == HANDLER_NAME:
            root.removeHandler(existing)
    handler = logging.StreamHandler(stream)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(SecretRedactingFilter())
    root.addHandler(handler)
    root.setLevel(level)
