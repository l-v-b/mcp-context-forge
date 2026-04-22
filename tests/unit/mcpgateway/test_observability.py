# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_observability.py
Copyright 2026
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Tests for observability module.
"""

# Standard
import importlib
import inspect
import os
from unittest.mock import MagicMock, patch

# Third-Party
import pytest

# First-Party
from mcpgateway import observability
from mcpgateway.config import get_settings
from mcpgateway.observability import (
    BaggageSpanAttributePolicy,
    configure_baggage_span_attribute_policy,
    OpenTelemetryRequestMiddleware,
    create_span,
    extract_baggage_span_attribute_policy,
    inject_trace_context_headers,
    init_telemetry,
    otel_context_active,
    otel_tracing_enabled,
    trace_operation,
)
from mcpgateway.utils.trace_context import clear_trace_context, set_trace_context_from_teams, set_trace_session_id


class TestObservability:
    """Test cases for observability module."""

    def setup_method(self):
        """Reset environment before each test."""
        get_settings.cache_clear()
        configure_baggage_span_attribute_policy()
        # Clear relevant environment variables
        env_vars = [
            "OTEL_ENABLE_OBSERVABILITY",
            "OTEL_TRACES_EXPORTER",
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "OTEL_EXPORTER_OTLP_HEADERS",
            "OTEL_EXPORTER_OTLP_INSECURE",
            "OTEL_EXPORTER_OTLP_PROTOCOL",
            "OTEL_EMIT_LANGFUSE_ATTRIBUTES",
            "OTEL_CAPTURE_IDENTITY_ATTRIBUTES",
            "LANGFUSE_OTEL_ENDPOINT",
            "LANGFUSE_OTEL_AUTH",
            "LANGFUSE_PUBLIC_KEY",
            "LANGFUSE_SECRET_KEY",
            "OTEL_COPY_RESOURCE_ATTRS_TO_SPANS",
        ]
        for var in env_vars:
            os.environ.pop(var, None)

        # Reset module-level state
        observability._TRACER = None

    def _enable_observability(self):
        """Helper to enable observability for tests."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "true"
        get_settings.cache_clear()

    def test_observability_disabled_by_default(self):
        """Test that observability is disabled by default."""
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_explicitly(self):
        """Test that observability can be explicitly disabled."""
        os.environ["OTEL_ENABLE_OBSERVABILITY"] = "false"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_with_none_exporter(self):
        """Test that observability is disabled when exporter is 'none'."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "none"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    def test_observability_disabled_without_otlp_endpoint(self):
        """Test that observability is disabled when OTLP endpoint is not configured."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", False)
    def test_observability_graceful_degradation_when_otel_not_installed(self):
        """Test graceful degradation when OpenTelemetry is not installed."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        get_settings.cache_clear()
        result = init_telemetry()
        assert result is None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        get_settings.cache_clear()

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        # Mock OTLP_SPAN_EXPORTER
        mock_exporter = MagicMock()
        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", mock_exporter):
            result = init_telemetry()

        # Verify exporter was created with correct endpoint
        mock_exporter.assert_called_once()
        call_kwargs = mock_exporter.call_args[1]
        assert call_kwargs["endpoint"] == "http://localhost:4317"
        assert result is not None

    def test_supports_exporter_kwarg_with_var_keyword(self):
        """Test _supports_exporter_kwarg returns True for exporters with **kwargs."""

        class ExporterWithKwargs:
            def __init__(self, endpoint=None, **kwargs):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithKwargs, "insecure") is True

    def test_supports_exporter_kwarg_with_explicit_param(self):
        """Test _supports_exporter_kwarg returns True when kwarg is explicitly defined."""

        class ExporterWithInsecure:
            def __init__(self, endpoint=None, insecure=False):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithInsecure, "insecure") is True

    def test_supports_exporter_kwarg_without_param(self):
        """Test _supports_exporter_kwarg returns False when kwarg is not supported."""

        class ExporterWithoutInsecure:
            def __init__(self, endpoint=None, headers=None):
                pass

        assert observability._supports_exporter_kwarg(ExporterWithoutInsecure, "insecure") is False

    def test_supports_exporter_kwarg_with_non_callable(self):
        """Test _supports_exporter_kwarg returns False for non-callable objects."""
        assert observability._supports_exporter_kwarg("not_a_callable", "insecure") is False
        assert observability._supports_exporter_kwarg(None, "insecure") is False
        assert observability._supports_exporter_kwarg(123, "insecure") is False

    def test_supports_exporter_kwarg_handles_typeerror(self):
        """Test _supports_exporter_kwarg handles TypeError from inspect.signature."""
        # Built-in types like int, str raise TypeError when inspect.signature is called
        assert observability._supports_exporter_kwarg(int, "insecure") is False
        assert observability._supports_exporter_kwarg(str, "insecure") is False
        assert observability._supports_exporter_kwarg(list, "insecure") is False

    def test_supports_exporter_kwarg_handles_valueerror(self):
        """Test _supports_exporter_kwarg handles ValueError from inspect.signature."""

        class ProblematicClass:
            """Class that causes ValueError when signature is inspected."""

            pass

        # Patch inspect.signature to raise ValueError
        with patch("inspect.signature", side_effect=ValueError("No signature available")):
            assert observability._supports_exporter_kwarg(ProblematicClass, "insecure") is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc_with_insecure_true(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter passes insecure=True when configured."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "collector.example.com:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"
        get_settings.cache_clear()

        class FakeGrpcExporter:
            """Exporter with the insecure constructor kwarg used by gRPC OTLP."""

            calls = []

            def __init__(self, endpoint=None, headers=None, insecure=False, **kwargs):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers, "insecure": insecure, "kwargs": kwargs})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", FakeGrpcExporter):
            result = init_telemetry()

        assert result is not None
        assert FakeGrpcExporter.calls[-1]["endpoint"] == "collector.example.com:4317"
        assert FakeGrpcExporter.calls[-1]["insecure"] is True

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_grpc_without_insecure_support(self, mock_processor, mock_provider):
        """Test OTLP gRPC exporter omits insecure kwarg when not supported by exporter."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "collector.example.com:4317"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "grpc"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"
        get_settings.cache_clear()

        class FakeGrpcExporter:
            """Exporter without insecure kwarg (older OTLP versions)."""

            calls = []

            def __init__(self, endpoint=None, headers=None):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", FakeGrpcExporter):
            result = init_telemetry()

        assert result is not None
        assert FakeGrpcExporter.calls[-1]["endpoint"] == "collector.example.com:4317"
        assert "insecure" not in FakeGrpcExporter.calls[-1]

    def test_otlp_http_exporter_kwargs_preserve_real_exporter_certificate_defaults(self):
        """Test that HTTP OTLP exporter kwargs do not pass unsupported insecure TLS flags."""
        http_exporter_mod = pytest.importorskip("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        exporter_cls = http_exporter_mod.OTLPSpanExporter

        kwargs = observability._otlp_exporter_kwargs(
            exporter_cls,
            endpoint="https://collector.example.com/v1/traces",
            headers=None,
            protocol="http",
            insecure=True,
        )

        assert kwargs == {"endpoint": "https://collector.example.com/v1/traces", "headers": None}

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.BatchSpanProcessor")
    def test_init_telemetry_otlp_http_keeps_certificate_file_unset_for_insecure_setting(self, mock_processor, mock_provider):
        """Test that HTTP OTLP exporters do not receive an ineffective certificate_file flag."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "otlp"
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "https://collector.example.com/v1/traces"
        os.environ["OTEL_EXPORTER_OTLP_PROTOCOL"] = "http"
        os.environ["OTEL_EXPORTER_OTLP_INSECURE"] = "true"

        class FakeHttpExporter:
            """Exporter with the certificate_file constructor kwarg used by HTTP OTLP."""

            calls = []

            def __init__(self, endpoint=None, headers=None, certificate_file="unset"):
                self.__class__.calls.append({"endpoint": endpoint, "headers": headers, "certificate_file": certificate_file})

        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        with patch("mcpgateway.observability.OTLP_SPAN_EXPORTER", None):
            with patch("mcpgateway.observability.HTTP_EXPORTER", FakeHttpExporter):
                result = init_telemetry()

        assert result is not None
        assert FakeHttpExporter.calls[-1]["endpoint"] == "https://collector.example.com/v1/traces"
        assert FakeHttpExporter.calls[-1]["certificate_file"] == "unset"

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_console_exporter(self, mock_processor, mock_provider, mock_exporter):
        """Test console exporter initialization."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify console exporter was created
        mock_exporter.assert_called_once()
        # Only 1 span processor (SimpleSpanProcessor) since OTEL_COPY_RESOURCE_ATTRS_TO_SPANS is not set
        provider_instance.add_span_processor.assert_called_once()
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_with_resource_attr_copy_enabled(self, mock_processor, mock_provider, mock_exporter):
        """Test that ResourceAttributeSpanProcessor is added when OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=true."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_COPY_RESOURCE_ATTRS_TO_SPANS"] = "true"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify 2 span processors: ResourceAttributeSpanProcessor + SimpleSpanProcessor
        assert provider_instance.add_span_processor.call_count == 2
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.ConsoleSpanExporter")
    @patch("mcpgateway.observability.TracerProvider")
    @patch("mcpgateway.observability.SimpleSpanProcessor")
    def test_init_telemetry_with_resource_attr_copy_disabled(self, mock_processor, mock_provider, mock_exporter):
        """Test that ResourceAttributeSpanProcessor is not added when OTEL_COPY_RESOURCE_ATTRS_TO_SPANS=false."""
        self._enable_observability()
        os.environ["OTEL_TRACES_EXPORTER"] = "console"
        os.environ["OTEL_COPY_RESOURCE_ATTRS_TO_SPANS"] = "false"

        # Mock the provider instance
        provider_instance = MagicMock()
        mock_provider.return_value = provider_instance

        result = init_telemetry()

        # Verify only 1 span processor (SimpleSpanProcessor)
        provider_instance.add_span_processor.assert_called_once()
        assert result is not None

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    def test_otel_tracing_enabled_when_tracer_initialized(self):
        """Test otel_tracing_enabled returns True when tracer is initialized."""
        observability._TRACER = MagicMock()
        assert otel_tracing_enabled() is True

    def test_otel_tracing_enabled_when_tracer_not_initialized(self):
        """Test otel_tracing_enabled returns False when tracer is not initialized."""
        observability._TRACER = None
        assert otel_tracing_enabled() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_valid_span(self, mock_trace):
        """Test otel_context_active returns True when there's a valid span."""
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.is_valid = True
        mock_span.get_span_context.return_value = mock_span_context
        mock_trace.get_current_span.return_value = mock_span

        assert otel_context_active() is True

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_invalid_span(self, mock_trace):
        """Test otel_context_active returns False when span is invalid."""
        mock_span = MagicMock()
        mock_span_context = MagicMock()
        mock_span_context.is_valid = False
        mock_span.get_span_context.return_value = mock_span_context
        mock_trace.get_current_span.return_value = mock_span

        assert otel_context_active() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", True)
    @patch("mcpgateway.observability.trace")
    def test_otel_context_active_with_no_span(self, mock_trace):
        """Test otel_context_active returns False when there's no current span."""
        mock_trace.get_current_span.return_value = None
        assert otel_context_active() is False

    @patch("mcpgateway.observability.OTEL_AVAILABLE", False)
    def test_otel_context_active_when_otel_not_available(self):
        """Test otel_context_active returns False when OpenTelemetry is not available."""
        assert otel_context_active() is False

    @patch("mcpgateway.observability.otel_context_active", return_value=True)
    @patch("mcpgateway.observability.otel_inject")
    def test_inject_trace_context_headers_injects_into_copy(self, mock_inject):
        """Test W3C trace context injection returns a copied carrier."""
        original = {"authorization": "Bearer abc"}

        def _fake_inject(carrier):
            carrier["traceparent"] = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
            carrier["tracestate"] = "vendor=value"

        mock_inject.side_effect = _fake_inject

        with patch("mcpgateway.observability.otel_context_active", return_value=True):
            carrier = inject_trace_context_headers(original)

        assert carrier["authorization"] == "Bearer abc"
        assert carrier["traceparent"].startswith("00-")
        assert carrier["tracestate"] == "vendor=value"
        assert "traceparent" not in original

    def test_inject_trace_context_headers_returns_copy_when_inactive(self):
        """Test inactive OTEL contexts do not mutate outbound headers."""
        original = {"authorization": "Bearer abc"}

        with patch("mcpgateway.observability.otel_context_active", return_value=False):
            carrier = inject_trace_context_headers(original)

        assert carrier == original
        assert carrier is not original

    @patch("mcpgateway.observability.otel_inject", side_effect=RuntimeError("boom"))
    def test_inject_trace_context_headers_logs_and_returns_headers_when_inject_fails(self, _mock_inject):
        """Test outbound headers survive OTEL propagation injection failures."""
        original = {"authorization": "Bearer abc"}

        with (
            patch("mcpgateway.observability.otel_context_active", return_value=True),
            patch("mcpgateway.observability.logger") as mock_logger,
        ):
            carrier = inject_trace_context_headers(original)

        assert carrier == original
        mock_logger.debug.assert_called_once()

    def test_scope_headers_to_carrier_skips_malformed_headers(self):
        """Test malformed ASGI header tuples are ignored during carrier conversion."""
        # First-Party
        import mcpgateway.observability

        carrier = mcpgateway.observability._scope_headers_to_carrier(
            [
                (b"user-agent", b"pytest"),
                ("bad-key", b"value"),
                (b"x-test", object()),
            ]
        )

        assert carrier == {"user-agent": "pytest"}

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/servers/demo/mcp", True),
            ("/servers/demo/message/", True),
            ("/_internal/mcp/plugin", True),
            ("/mcp/sse", True),
            ("/mcp/message", True),
            ("/mcp/sse/", True),
            ("/mcp/message/", True),
            ("/health", False),
            ("/mcp/unknown", False),
        ],
    )
    def test_should_trace_request_path_handles_transport_variants(self, path, expected):
        """Test transport-specific request paths are selected for tracing."""
        # First-Party
        import mcpgateway.observability

        assert mcpgateway.observability._should_trace_request_path(path) is expected

    def test_open_telemetry_request_middleware_proxies_app_attributes(self):
        """Test middleware proxies attribute access to the wrapped app."""

        class AppWithRouteMarker:
            routes = ["route-a"]

        middleware = OpenTelemetryRequestMiddleware(AppWithRouteMarker())
        assert middleware.routes == ["route-a"]

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_skips_untraced_http_paths(self):
        """Test OTEL request middleware ignores non-transport HTTP paths."""
        sent_messages = []

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        tracer = MagicMock()

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        scope = {
            "type": "http",
            "method": "GET",
            "path": "/v1/admin",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_not_called()
        assert sent_messages[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_supports_custom_path_filter(self):
        """Test OTEL request middleware can be reused with runtime-specific path filters."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        middleware = OpenTelemetryRequestMiddleware(app, should_trace_request_path=lambda path: path == "/custom")
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/custom",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    @patch("mcpgateway.observability.otel_extract", return_value="parent-context")
    async def test_open_telemetry_request_middleware_creates_server_span(self, mock_extract):
        """Test OTEL request middleware creates a root server span for /rpc."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/rpc",
            "headers": [
                (b"user-agent", b"pytest"),
                (b"x-correlation-id", b"corr-123"),
                (b"traceparent", b"00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"),
            ],
            "query_string": b"server_id=abc",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once_with(
            "POST /rpc",
            context="parent-context",
            kind=mcpgateway.observability.SpanKind.SERVER,
        )
        mock_extract.assert_called_once()
        span.set_attribute.assert_any_call("http.request.method", "POST")
        span.set_attribute.assert_any_call("http.route", "/rpc")
        # Query string is now sanitized - non-sensitive params remain visible
        span.set_attribute.assert_any_call("url.query", "server_id=abc")
        span.set_attribute.assert_any_call("user_agent.original", "pytest")
        span.set_attribute.assert_any_call("correlation_id", "corr-123")
        span.set_attribute.assert_any_call("http.response.status_code", 200)
        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_records_exceptions(self):
        """Test OTEL request middleware records exceptions on the root span."""
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        class DummyStatusCode:
            ERROR = "error"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            raise RuntimeError("boom")

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/rpc",
            "headers": [],
            "query_string": b"",
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            return None

        with patch("mcpgateway.observability.OTEL_AVAILABLE", True):
            with patch("mcpgateway.observability.Status", DummyStatus):
                with patch("mcpgateway.observability.StatusCode", DummyStatusCode):
                    with pytest.raises(RuntimeError, match="boom"):
                        await middleware(scope, receive, send)

        span.add_event.assert_called_once()
        span.set_attribute.assert_any_call("error", True)
        span.set_attribute.assert_any_call("error.type", "RuntimeError")
        span.set_attribute.assert_any_call("error.message", "boom")
        status_arg = span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.ERROR

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_tolerates_extract_failures_and_non_bytes_query(self):
        """Test middleware continues tracing when parent extraction fails."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        class DummyStatusCode:
            OK = "ok"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/servers/plugin-a/mcp",
            "headers": [(b"user-agent", b"pytest"), ("broken", b"value")],
            "query_string": "trace=1",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        with (
            patch("mcpgateway.observability.otel_extract", side_effect=RuntimeError("bad parent")),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.Status", DummyStatus),
            patch("mcpgateway.observability.StatusCode", DummyStatusCode),
        ):
            await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        span.set_attribute.assert_any_call("http.request.method", "GET")
        span.set_attribute.assert_any_call("url.query", "trace=1")
        span.set_status.assert_called_once()
        assert sent_messages[0]["status"] == 204

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_redacts_session_id_in_query_string(self):
        """Test middleware redacts session_id from query strings to prevent leaking live sessions."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        middleware = OpenTelemetryRequestMiddleware(app)

        # Simulate SSE callback URL with session_id in query string
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/message",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": b"session_id=live-session-abc123&other=value",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        await middleware(scope, receive, send)

        # Verify session_id was redacted in the span attribute
        span.set_attribute.assert_any_call("http.request.method", "POST")
        span.set_attribute.assert_any_call("http.route", "/message")

        # Check that session_id is redacted but other params remain
        query_calls = [call for call in span.set_attribute.call_args_list if call[0][0] == "url.query"]
        assert len(query_calls) == 1
        query_value = query_calls[0][0][1]

        # session_id should be redacted
        assert "live-session-abc123" not in query_value
        assert "session_id=***" in query_value or "sessionid=***" in query_value.lower()

        # Non-sensitive params should remain visible
        assert "other=value" in query_value

        assert sent_messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_open_telemetry_request_middleware_tolerates_extract_failures_continued(self):
        """Test middleware continues after extraction failures."""
        sent_messages = []
        span = MagicMock()
        span_context = MagicMock()
        span_context.__enter__ = MagicMock(return_value=span)
        span_context.__exit__ = MagicMock(return_value=None)
        tracer = MagicMock()
        tracer.start_as_current_span.return_value = span_context

        # First-Party
        import mcpgateway.observability

        # pylint: disable=protected-access
        mcpgateway.observability._TRACER = tracer

        class DummyStatusCode:
            OK = "ok"

        class DummyStatus:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        async def app(scope, receive, send):
            await send({"type": "http.response.start", "status": 204, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        middleware = OpenTelemetryRequestMiddleware(app)
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/servers/plugin-a/mcp",
            "headers": [(b"user-agent", b"pytest")],
            "query_string": "trace=1",
            "http_version": "1.1",
            "server": ("localhost", 4444),
            "client": ("127.0.0.1", 51234),
        }

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent_messages.append(message)

        with (
            patch("mcpgateway.observability.otel_extract", side_effect=RuntimeError("bad parent")),
            patch("mcpgateway.observability.OTEL_AVAILABLE", True),
            patch("mcpgateway.observability.Status", DummyStatus),
            patch("mcpgateway.observability.StatusCode", DummyStatusCode),
            patch("mcpgateway.observability.logger") as mock_logger,
        ):
            await middleware(scope, receive, send)

        tracer.start_as_current_span.assert_called_once()
        span.set_attribute.assert_any_call("http.response.status_code", 204)
        status_arg = span.set_status.call_args[0][0]
        assert isinstance(status_arg, DummyStatus)
        assert status_arg.code == DummyStatusCode.OK
        assert sent_messages[0]["status"] == 204
        mock_logger.debug.assert_called_once()

    def test_observability_module_imports_otel_symbols_when_dependency_present(self):
        """Test module import path binds OTEL symbols when OpenTelemetry imports succeed."""
        # First-Party
        import mcpgateway.observability as observability

        fake_trace = object()
        fake_extract = object()
        fake_inject = object()
        fake_resource = object()
        fake_tracer_provider = object()
        fake_batch = object()
        fake_console = object()
        fake_simple = object()
        fake_span_kind = object()
        fake_status = object()
        fake_status_code = object()

        original_import = importlib.import_module

        def _fake_import(name, package=None):
            if name == "opentelemetry.exporter.otlp.proto.http.trace_exporter":
                return type("FakeOTLPModule", (), {"OTLPSpanExporter": object()})()
            return original_import(name, package)

        with (
            patch.object(observability, "_im", side_effect=_fake_import),
            patch.dict(
                "sys.modules",
                {
                    "opentelemetry": type("FakeOtel", (), {"trace": fake_trace})(),
                    "opentelemetry.propagate": type("FakePropagate", (), {"extract": fake_extract, "inject": fake_inject})(),
                    "opentelemetry.sdk.resources": type("FakeResources", (), {"Resource": fake_resource})(),
                    "opentelemetry.sdk.trace": type("FakeSDKTrace", (), {"TracerProvider": fake_tracer_provider})(),
                    "opentelemetry.sdk.trace.export": type(
                        "FakeSDKTraceExport",
                        (),
                        {
                            "BatchSpanProcessor": fake_batch,
                            "ConsoleSpanExporter": fake_console,
                            "SimpleSpanProcessor": fake_simple,
                        },
                    )(),
                    "opentelemetry.trace": type(
                        "FakeTraceModule",
                        (),
                        {
                            "SpanKind": fake_span_kind,
                            "Status": fake_status,
                            "StatusCode": fake_status_code,
                        },
                    )(),
                },
                clear=False,
            ),
        ):
            reloaded = importlib.reload(observability)

        try:
            assert reloaded.OTEL_AVAILABLE is True
            assert reloaded.trace is fake_trace
            assert reloaded.otel_extract is fake_extract
            assert reloaded.otel_inject is fake_inject
            assert reloaded.SpanKind is fake_span_kind
        finally:
            importlib.reload(reloaded)
