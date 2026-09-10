"""
Structured logging setup.

Every log call across the app already uses structlog.get_logger() — this
module is what actually configures how those calls render, and adds a
request-scoped context (request_id, method, path) so a single grep on a
request_id pulls every log line for that request across routers/agents/
ingestion, not just whichever module happened to log last.

LOG_LEVEL env var controls verbosity (default INFO). Set LOG_JSON=1 for
machine-parseable JSON output (useful piping into a log aggregator);
otherwise renders as readable colored console output — the better
default for `docker compose logs -f backend` during development.
"""
import logging
import os
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def configure_logging():
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    json_output = os.environ.get("LOG_JSON", "0") == "1"

    logging.basicConfig(format="%(message)s", level=level)
    # Quiet down noisy third-party loggers unless we're at DEBUG
    if level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "neo4j", "urllib3", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Logs every request's method/path/status/duration and binds a
    request_id into structlog's contextvars so every log emitted while
    handling this request — in the router, in the agent graph, in
    ingestion — carries the same id without having to thread it through
    every function signature."""

    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id, method=request.method, path=request.url.path,
        )
        logger = structlog.get_logger()
        t0 = time.time()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed", duration_ms=round((time.time() - t0) * 1000, 1))
            raise
        duration_ms = round((time.time() - t0) * 1000, 1)
        log = logger.info if response.status_code < 500 else logger.error
        # SSE endpoints (StreamingResponse) log at request start via this line;
        # duration here reflects time to first byte, not full stream duration.
        log("request_done", status=response.status_code, duration_ms=duration_ms)
        response.headers["X-Request-ID"] = request_id
        return response
