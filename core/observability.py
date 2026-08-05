from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
_ROOT = Path(__file__).resolve().parent.parent
_SENTRY_INITIALIZED = False
logger = logging.getLogger(__name__)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        corr = correlation_id()
        if corr:
            payload["correlation_id"] = corr
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def log_timing(metric: str, duration_ms: float, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "metric": metric,
        "duration_ms": round(float(duration_ms), 2),
        **fields,
    }
    corr = correlation_id()
    if corr:
        payload["correlation_id"] = corr
    logging.getLogger("core.metrics").info("timing %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    timing_path = Path(
        str(os.environ.get("II_TIMING_LOG_PATH") or (_ROOT / "data" / "reports" / "logs" / "timing_metrics.jsonl"))
    )
    try:
        timing_path.parent.mkdir(parents=True, exist_ok=True)
        with timing_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        logger.debug("timing_log_write_failed path=%s", timing_path, exc_info=True)


@contextlib.contextmanager
def timed_operation(metric: str, **fields: Any):
    start = perf_counter()
    try:
        yield
    finally:
        log_timing(metric, (perf_counter() - start) * 1000.0, **fields)


def correlation_id() -> str:
    return _correlation_id_var.get()


def ensure_correlation_id(seed: str = "") -> str:
    existing = correlation_id()
    if existing:
        return existing
    cid = str(seed or os.environ.get("II_CORRELATION_ID") or uuid.uuid4().hex)
    _correlation_id_var.set(cid)
    return cid


def init_sentry(component: str = "app") -> bool:
    """
    Initialize Sentry when II_SENTRY_DSN is set.
    Safe no-op when DSN missing or sentry-sdk not installed.
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return True
    dsn = str(os.environ.get("II_SENTRY_DSN") or "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        logger.warning("II_SENTRY_DSN set but sentry-sdk is not installed")
        return False

    try:
        sample = float(os.environ.get("II_SENTRY_TRACES_SAMPLE_RATE", "0.0") or "0.0")
    except ValueError:
        sample = 0.0
    env_name = str(os.environ.get("II_ENV") or os.environ.get("SENTRY_ENVIRONMENT") or "dev").strip() or "dev"
    release = str(os.environ.get("II_SENTRY_RELEASE") or os.environ.get("II_APP_VERSION") or "").strip() or None

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=env_name,
            release=release,
            traces_sample_rate=max(0.0, min(1.0, sample)),
            send_default_pii=False,
            integrations=[
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
        )
        sentry_sdk.set_tag("component", str(component or "app"))
        _SENTRY_INITIALIZED = True
        logger.info("sentry_initialized component=%s environment=%s", component, env_name)
        return True
    except Exception:
        logger.exception("sentry_init_failed component=%s", component)
        return False


def capture_exception(exc: BaseException | None = None, **scope_attrs: Any) -> None:
    """Forward exception to Sentry when configured; always safe to call."""
    if not _SENTRY_INITIALIZED:
        return
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            for k, v in scope_attrs.items():
                scope.set_extra(str(k), v)
            if exc is None:
                sentry_sdk.capture_exception()
            else:
                sentry_sdk.capture_exception(exc)
    except Exception:
        logger.debug("sentry_capture_exception_failed", exc_info=True)


def configure_observability(component: str = "app") -> str:
    root = logging.getLogger()
    level_name = str(os.environ.get("II_LOG_LEVEL", "INFO")).strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)

    if not root.handlers:
        handler = logging.StreamHandler()
        if str(os.environ.get("II_LOG_JSON", "1")).strip().lower() in ("0", "false", "no", "off"):
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        else:
            handler.setFormatter(JsonFormatter())
        root.addHandler(handler)

    init_sentry(component)
    cid = ensure_correlation_id(component)
    logger.info("observability_configured component=%s", component)
    return cid
