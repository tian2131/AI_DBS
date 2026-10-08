"""Request tracing and context propagation for PostgreSQL MCP Server.

This module provides request ID generation and context propagation throughout
the query processing pipeline via context variables, enabling end-to-end
tracing of requests. A logging filter (see observability.logging) injects the
current request ID into every log record automatically.
"""

import contextvars
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from pydantic import BaseModel

# Context variable for current request ID
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class TraceContext(BaseModel):
    """Trace context containing request tracking information.

    Attributes:
        request_id: Unique identifier for the request.
        parent_id: Optional parent request ID for nested operations.
        operation: Name of the operation being traced.
        metadata: Additional metadata about the request.
    """

    request_id: str
    parent_id: str | None = None
    operation: str | None = None
    metadata: dict[str, Any] | None = None


def generate_request_id() -> str:
    """Generate a unique request ID.

    Returns:
        UUID4-based request ID as a string.

    Example:
        >>> req_id = generate_request_id()
        >>> print(req_id)
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    """
    return str(uuid.uuid4())


def get_request_id() -> str | None:
    """Get the current request ID from context.

    Returns:
        Current request ID or None if not set.

    Example:
        >>> with request_context():
        ...     print(get_request_id())
        'a1b2c3d4-e5f6-7890-abcd-ef1234567890'
    """
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set the current request ID in context.

    Args:
        request_id: Request ID to set.

    Example:
        >>> set_request_id("custom-request-id")
        >>> assert get_request_id() == "custom-request-id"
    """
    _request_id_var.set(request_id)


def clear_request_id() -> None:
    """Clear the current request ID from context.

    Example:
        >>> clear_request_id()
        >>> assert get_request_id() is None
    """
    _request_id_var.set(None)


@asynccontextmanager
async def request_context(request_id: str | None = None) -> AsyncIterator[str]:
    """Context manager for request tracing.

    Creates a new request context with a unique (or provided) request ID
    that will be propagated through all async operations.

    Args:
        request_id: Optional request ID. If not provided, a new one is generated.

    Yields:
        The request ID for this context.

    Example:
        >>> async with request_context() as req_id:
        ...     logger.info("Processing request")
        ...     await some_operation()
    """
    if request_id is None:
        request_id = generate_request_id()

    token = _request_id_var.set(request_id)
    try:
        yield request_id
    finally:
        _request_id_var.reset(token)
