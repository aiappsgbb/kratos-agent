"""OpenTelemetry setup for distributed tracing and metrics."""

import logging
import os

from fastapi import FastAPI
from opentelemetry import _logs, metrics, trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from app.config import Settings

logger = logging.getLogger(__name__)

# HTTP methods we want to keep in traces (everything else is noise)
_TRACED_HTTP_METHODS = frozenset({"GET", "POST"})


class FilteringSpanProcessor(BatchSpanProcessor):
    """BatchSpanProcessor that silently drops noisy spans before export.

    Filters out:
    - ASGI internal send/receive spans (kind=INTERNAL, name contains 'http send'
      or 'http receive') that create duplicate InProcess entries for SSE streams.
    - HTTP spans for methods other than GET/POST (OPTIONS, PATCH, DELETE, …).
    """

    def __init__(self, exporter: SpanExporter, **kwargs) -> None:
        super().__init__(exporter, **kwargs)

    def on_end(self, span: ReadableSpan) -> None:
        # Drop ASGI internal send/receive spans
        if span.kind == trace.SpanKind.INTERNAL:
            name = span.name
            if "http send" in name or "http receive" in name:
                return

        # Drop HTTP spans for methods we don't care about
        attrs = span.attributes or {}
        http_method = attrs.get("http.request.method") or attrs.get("http.method")
        if http_method and http_method.upper() not in _TRACED_HTTP_METHODS:
            return

        super().on_end(span)


# GenAI metric bucket boundaries per OTel semantic conventions
_TOKEN_BUCKETS = (1, 4, 16, 64, 256, 1024, 4096, 16384, 65536, 262144, 1048576, 4194304, 16777216, 67108864)
_DURATION_BUCKETS = (0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.28, 2.56, 5.12, 10.24, 20.48, 40.96, 81.92)

# Module-level reference for the tracer provider (used by instrument_fastapi_app)
_tracer_provider: TracerProvider | None = None


def setup_telemetry(settings: Settings) -> None:
    """Configure OpenTelemetry with Azure Monitor exporters (traces, metrics, logs/events)."""
    global _tracer_provider

    resource = Resource.create(
        {
            "service.name": settings.otel_service_name,
            "service.version": "0.1.0",
            "deployment.environment": settings.environment,
        }
    )

    provider = TracerProvider(resource=resource)

    if settings.applicationinsights_connection_string:
        try:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorLogExporter,
                AzureMonitorMetricExporter,
                AzureMonitorTraceExporter,
            )

            conn_str = settings.applicationinsights_connection_string

            # Traces → AppInsights 'dependencies' and 'requests' tables
            trace_exporter = AzureMonitorTraceExporter(connection_string=conn_str)
            provider.add_span_processor(FilteringSpanProcessor(trace_exporter))
            logger.info("Azure Monitor trace exporter configured")

            # Metrics → AppInsights 'customMetrics' table
            metric_exporter = AzureMonitorMetricExporter(connection_string=conn_str)
            metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=60000)
            meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
            metrics.set_meter_provider(meter_provider)
            logger.info("Azure Monitor metric exporter configured")

            # Logs/Events → AppInsights 'traces' and 'customEvents' tables
            log_exporter = AzureMonitorLogExporter(connection_string=conn_str)
            log_provider = LoggerProvider(resource=resource)
            log_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
            _logs.set_logger_provider(log_provider)

            # Bridge Python logging → OTel Logs → AppInsights 'traces' table.
            # This captures all app logs (copilot_agent events, skill calls, etc.)
            # and correlates them with the active trace context.
            otel_handler = LoggingHandler(level=logging.INFO, logger_provider=log_provider)
            logging.getLogger().addHandler(otel_handler)
            logger.info("Azure Monitor log/events exporter configured (with Python logging bridge)")

        except Exception:
            logger.warning("Failed to configure Azure Monitor exporters", exc_info=True)

    trace.set_tracer_provider(provider)
    _tracer_provider = provider

    # Instrument OpenAI SDK for Foundry model call tracing
    try:
        from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor

        OpenAIInstrumentor().instrument(tracer_provider=provider)
        logger.info("OpenAI SDK tracing instrumented")
    except Exception:
        logger.warning("Failed to instrument OpenAI SDK — model call traces will not be captured")

    # Enable GenAI content recording if the env var is set
    if os.environ.get("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "").lower() == "true":
        logger.info("GenAI content recording enabled — prompts and completions will be captured in traces")

    logger.info("OpenTelemetry initialized — service=%s", settings.otel_service_name)


def instrument_fastapi_app(app: FastAPI) -> None:
    """Instrument a specific FastAPI app instance for HTTP request tracing.

    Must be called AFTER the FastAPI app is created but BEFORE the first request.
    Uses the global tracer provider (set later by setup_telemetry via the lifespan).
    The OpenTelemetry ProxyTracerProvider ensures spans are routed correctly once
    the real provider is configured.
    """
    FastAPIInstrumentor.instrument_app(app)
    logger.info("FastAPI app instrumented for HTTP request tracing")


# ── GenAI Metrics ────────────────────────────────────────────────────────────
# Expose histograms per OTel GenAI semantic conventions so copilot_agent.py can
# record token usage and operation duration without coupling to the exporter setup.

_meter = metrics.get_meter("kratos-agent", "0.1.0")

token_usage_histogram = _meter.create_histogram(
    name="gen_ai.client.token.usage",
    description="Number of input and output tokens used",
    unit="{token}",
)

operation_duration_histogram = _meter.create_histogram(
    name="gen_ai.client.operation.duration",
    description="GenAI operation duration",
    unit="s",
)
