"""Unit tests for observability: tracing context and log record injection.

Tests the request-ID context variables, the RequestIdFilter that injects
the context request ID into log records, and the logging configuration
that wires the filter into handlers.
"""

import json
import logging

import pytest

from pg_mcp.observability.logging import (
    JSONFormatter,
    RequestIdFilter,
    TextFormatter,
    configure_logging,
)
from pg_mcp.observability.tracing import (
    clear_request_id,
    generate_request_id,
    get_request_id,
    request_context,
    set_request_id,
)


def _make_record(msg: str = "hello") -> logging.LogRecord:
    """Create a bare log record without a request_id attribute."""
    return logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestTracingContext:
    """Tests for request ID context management."""

    def test_generate_request_id_returns_uuid_string(self) -> None:
        """Test generated request IDs are non-empty and unique."""
        first = generate_request_id()
        second = generate_request_id()
        assert first
        assert second
        assert first != second

    def test_get_request_id_defaults_to_none(self) -> None:
        """Test request ID is None outside any request context."""
        clear_request_id()
        assert get_request_id() is None

    def test_set_and_clear_request_id(self) -> None:
        """Test manual set/clear of the request ID."""
        set_request_id("manual-id")
        assert get_request_id() == "manual-id"
        clear_request_id()
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_request_context_yields_provided_id(self) -> None:
        """Test the context manager yields the provided request ID."""
        async with request_context("my-req-id") as request_id:
            assert request_id == "my-req-id"
            assert get_request_id() == "my-req-id"
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_request_context_generates_id_when_omitted(self) -> None:
        """Test a fresh request ID is generated when none is provided."""
        async with request_context() as request_id:
            assert request_id
            assert get_request_id() == request_id
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_nested_request_context_restores_outer(self) -> None:
        """Test exiting an inner context restores the outer request ID."""
        async with request_context("outer-id"):
            async with request_context("inner-id"):
                assert get_request_id() == "inner-id"
            assert get_request_id() == "outer-id"
        assert get_request_id() is None

    @pytest.mark.asyncio
    async def test_request_context_restores_on_exception(self) -> None:
        """Test the request ID is reset even when the body raises."""
        with pytest.raises(RuntimeError, match="boom"):
            async with request_context("error-id"):
                raise RuntimeError("boom")
        assert get_request_id() is None


class TestRequestIdFilter:
    """Tests for the log record request ID filter."""

    def test_filter_injects_context_request_id(self) -> None:
        """Test the filter attaches the context request ID to the record."""
        set_request_id("req-42")
        try:
            record = _make_record()
            assert RequestIdFilter().filter(record) is True
            assert record.request_id == "req-42"
        finally:
            clear_request_id()

    def test_filter_skips_when_no_context(self) -> None:
        """Test the filter leaves records untouched without a context ID."""
        clear_request_id()
        record = _make_record()
        assert RequestIdFilter().filter(record) is True
        assert not hasattr(record, "request_id")

    def test_filter_does_not_override_explicit_request_id(self) -> None:
        """Test an explicitly set record request_id wins over the context."""
        set_request_id("context-id")
        try:
            record = _make_record()
            record.request_id = "explicit-id"  # type: ignore[attr-defined]
            RequestIdFilter().filter(record)
            assert record.request_id == "explicit-id"
        finally:
            clear_request_id()


class TestFormatters:
    """Tests for request ID rendering in formatters."""

    def test_text_formatter_appends_request_id(self) -> None:
        """Test the text formatter renders the request ID."""
        record = _make_record()
        record.request_id = "req-7"  # type: ignore[attr-defined]
        text = TextFormatter().format(record)
        assert "[request_id=req-7]" in text

    def test_text_formatter_omits_missing_request_id(self) -> None:
        """Test the text formatter works without a request ID."""
        text = TextFormatter().format(_make_record())
        assert "request_id" not in text

    def test_json_formatter_includes_request_id(self) -> None:
        """Test the JSON formatter serializes the request ID."""
        record = _make_record()
        record.request_id = "req-8"  # type: ignore[attr-defined]
        data = json.loads(JSONFormatter().format(record))
        assert data["request_id"] == "req-8"


class TestConfigureLogging:
    """Tests for the logging configuration wiring."""

    def test_configure_logging_attaches_request_id_filter(self) -> None:
        """Test configure_logging wires RequestIdFilter into the handler."""
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        try:
            configure_logging(level="INFO", log_format="text", enable_sensitive_filter=False)
            assert len(root.handlers) == 1
            handler = root.handlers[0]
            request_id_filters = [
                f for f in handler.filters if isinstance(f, RequestIdFilter)
            ]
            assert len(request_id_filters) == 1
        finally:
            for stale in root.handlers[:]:
                root.removeHandler(stale)
            for original in original_handlers:
                root.addHandler(original)

    def test_configured_handler_injects_request_id(self) -> None:
        """Test records emitted through a filtered handler carry the context ID."""
        records: list[logging.LogRecord] = []

        class CaptureHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = CaptureHandler()
        handler.addFilter(RequestIdFilter())
        logger = logging.getLogger("test.observability.wiring")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            set_request_id("wired-req-1")
            try:
                logger.info("captured message")
            finally:
                clear_request_id()
        finally:
            logger.removeHandler(handler)

        assert len(records) == 1
        assert getattr(records[0], "request_id", None) == "wired-req-1"
