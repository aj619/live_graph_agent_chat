"""Langfuse tracing helpers (plan §6.6 and §6.9).

Two helpers, both controlled by `settings.LANGFUSE_ENABLED`:

- `get_callback_handlers()` returns the LangChain callback list for an LLM or
  agent run. It is `[CallbackHandler()]` when tracing is enabled and `[]` when
  it is disabled. Callers spread it into `config={"callbacks": [...]}`.
- `observe` is the Langfuse `@observe` decorator, applied only when tracing is
  enabled. When tracing is disabled it returns the function object unchanged.

The enabled check runs once, when a decorator is applied (at import time for a
module-level function). It does not run per call. Changing LANGFUSE_ENABLED
therefore needs a process restart, as with every other Settings value.

The Langfuse SDK reads LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY from os.environ. config.py exports them there at import
time, so they are not passed here. Neither helper contacts a server when it is
constructed or applied.
"""

from collections.abc import Callable
from typing import Any

from langfuse import observe as langfuse_observe
from langfuse.langchain import CallbackHandler

from app.config import settings


def get_callback_handlers() -> list[Any]:
    """Return the callbacks to attach to a LangChain run, or an empty list when tracing is off."""
    if not settings.LANGFUSE_ENABLED:
        return []
    return [CallbackHandler()]


def observe[F: Callable[..., Any]](
    func: F | None = None, *, name: str | None = None
) -> F | Callable[[F], F]:
    """Apply the Langfuse `@observe` decorator when tracing is enabled, otherwise do nothing.

    Usable bare (`@observe`) or with arguments (`@observe(name="...")`). The
    enabled check happens when the decorator is applied, not when the decorated
    function is called. When disabled, the original function object is returned,
    so there is no wrapper and no per-call cost.
    """

    def decorate(target: F) -> F:
        if not settings.LANGFUSE_ENABLED:
            return target
        return langfuse_observe(name=name)(target)

    if func is not None:
        return decorate(func)
    return decorate
