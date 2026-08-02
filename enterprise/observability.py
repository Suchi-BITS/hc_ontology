"""Observability — LangSmith tracing + OpenTelemetry spans."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("healthcare_ontology.observability")

_otel_tracer = None
_configured = False


def configure_observability() -> dict[str, Any]:
    """Configure LangSmith env + optional OTEL exporter. Idempotent."""
    global _configured, _otel_tracer
    from core.config import get_settings

    settings = get_settings()
    status: dict[str, Any] = {
        "langsmith": False,
        "otel": False,
        "project": settings.get("langchain_project"),
    }

    # LangSmith / LangChain tracing via environment (picked up by langchain)
    if settings.get("langchain_api_key"):
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true" if settings.get("langchain_tracing") else "false")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings["langchain_api_key"])
        os.environ.setdefault("LANGCHAIN_PROJECT", settings.get("langchain_project") or "healthcare-ontology-agents")
        if settings.get("langsmith_endpoint"):
            os.environ.setdefault("LANGSMITH_ENDPOINT", settings["langsmith_endpoint"])
        status["langsmith"] = settings.get("langchain_tracing", False)
        logger.info(
            "LangSmith tracing=%s project=%s",
            status["langsmith"],
            settings.get("langchain_project"),
        )
    else:
        logger.info("LangSmith API key not set — tracing disabled")

    if settings.get("otel_enabled"):
        try:
            from opentelemetry import trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

            resource = Resource.create(
                {
                    "service.name": settings.get("otel_service_name") or "healthcare-ontology-api",
                    "deployment.environment": settings.get("environment") or "development",
                }
            )
            provider = TracerProvider(resource=resource)
            endpoint = settings.get("otel_exporter_otlp_endpoint") or ""
            if endpoint:
                try:
                    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                        OTLPSpanExporter,
                    )

                    provider.add_span_processor(
                        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
                    )
                    status["otel_exporter"] = "otlp"
                except Exception as exc:
                    logger.warning("OTLP exporter unavailable (%s); using console", exc)
                    provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
                    status["otel_exporter"] = "console"
            else:
                # No endpoint: still enable tracer for local spans (no noisy console by default)
                status["otel_exporter"] = "noop"
            trace.set_tracer_provider(provider)
            _otel_tracer = trace.get_tracer("healthcare.ontology")
            status["otel"] = True
        except Exception as exc:
            logger.warning("OpenTelemetry setup failed: %s", exc)
            status["otel_error"] = str(exc)

    _configured = True
    return status


@contextmanager
def trace_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[Any]:
    """Open an OTEL span when available; otherwise no-op."""
    if _otel_tracer is None:
        yield None
        return
    with _otel_tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                if v is not None:
                    try:
                        span.set_attribute(k, v)
                    except Exception:
                        span.set_attribute(k, str(v))
        yield span


def langsmith_run_url(run_id: str | None = None) -> str | None:
    from core.config import get_settings

    project = get_settings().get("langchain_project") or "healthcare-ontology-agents"
    base = "https://smith.langchain.com"
    if run_id:
        return f"{base}/o/default/projects/p/{project}/r/{run_id}"
    return f"{base}/projects"
