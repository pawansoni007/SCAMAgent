"""Per-request debug tracing for local development diagnostics."""

from __future__ import annotations

import contextvars
import functools
import inspect
from collections.abc import Callable
from typing import Any

_debug_trace: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "scm_debug_trace",
    default=None,
)


def begin_debug_trace() -> contextvars.Token:
    """Start collecting debug calls in the current request context."""
    return _debug_trace.set([])


def end_debug_trace(token: contextvars.Token) -> list[dict[str, Any]]:
    """Stop collecting debug calls and return all captured entries."""
    calls = _debug_trace.get() or []
    _debug_trace.reset(token)
    return calls


def is_debug_trace_active() -> bool:
    return _debug_trace.get() is not None


def record_debug_call(
    kind: str,
    name: str,
    *,
    arguments: dict[str, Any] | None = None,
    entity: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    calls = _debug_trace.get()
    if calls is None:
        return

    entry: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "arguments": _safe_values(arguments or {}),
    }
    if entity:
        entry["entity"] = entity
    if metadata:
        entry["metadata"] = _safe_values(metadata)
    calls.append(entry)


def traced_function(kind: str = "method", entity: str | None = None):
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            record_debug_call(
                kind,
                func.__name__,
                arguments=_bind_arguments(func, args, kwargs),
                entity=entity,
            )
            return func(*args, **kwargs)

        return wrapper

    return decorator


def _bind_arguments(func: Callable, args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(func).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except Exception:
        return {}


def _safe_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: _safe_value(value) for key, value in values.items()}


def _safe_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    return str(value)
