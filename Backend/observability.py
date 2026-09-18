"""Run context, structured events, and metered Groq calls."""

import contextvars
import json
import logging
import os
import time
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from dotenv import load_dotenv

from storage import add_event, add_usage

load_dotenv(Path(__file__).resolve().parent / ".env")

logger = logging.getLogger("vaultlearn")
if not logger.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

_run_id = contextvars.ContextVar("run_id", default=None)
_session_id = contextvars.ContextVar("session_id", default=None)

# USD per million tokens; defaults from Groq's published model pricing.
_prices = {
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
}
if os.getenv("GROQ_PRICES_JSON"):
    _prices.update({key: tuple(value) for key, value in json.loads(os.environ["GROQ_PRICES_JSON"]).items()})


@contextmanager
def run_context(run_id: str, session_id: str | None = None):
    run_token = _run_id.set(run_id)
    session_token = _session_id.set(session_id)
    try:
        yield
    finally:
        _session_id.reset(session_token)
        _run_id.reset(run_token)


def event(name: str, *, status: str = "ok", duration_ms: float | None = None, details: dict | None = None):
    run_id = _run_id.get()
    if run_id:
        add_event(run_id, _session_id.get(), name, status, duration_ms, details or {})
    logger.info("event=%s status=%s run_id=%s session_id=%s duration_ms=%s", name, status, run_id, _session_id.get(), duration_ms)


def traced_node(name: str):
    def decorate(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.perf_counter()
            event(f"{name}.started")
            try:
                result = await func(*args, **kwargs)
            except Exception as exc:
                event(f"{name}.failed", status="error", duration_ms=(time.perf_counter() - start) * 1000, details={"error_type": type(exc).__name__})
                raise
            event(f"{name}.completed", duration_ms=(time.perf_counter() - start) * 1000)
            return result
        return wrapper
    return decorate


def _usage(raw):
    usage = getattr(raw, "usage_metadata", None) or {}
    response = getattr(raw, "response_metadata", None) or {}
    token_usage = response.get("token_usage", {})
    return (
        usage.get("input_tokens", token_usage.get("prompt_tokens")),
        usage.get("output_tokens", token_usage.get("completion_tokens")),
    )


async def tracked_invoke(runnable, messages, *, model: str, operation: str):
    start = time.perf_counter()
    status = "ok"
    raw = None
    try:
        result = await runnable.ainvoke(messages)
        raw = result.get("raw") if isinstance(result, dict) and "raw" in result else result
        if isinstance(result, dict) and result.get("parsing_error"):
            raise result["parsing_error"]
        if isinstance(result, dict) and "parsed" in result and result["parsed"] is None:
            raise ValueError(f"Structured response for {operation} could not be parsed")
        return result.get("parsed") if isinstance(result, dict) and "parsed" in result else result
    except Exception:
        status = "error"
        raise
    finally:
        input_tokens, output_tokens = _usage(raw) if raw is not None else (None, None)
        prices = _prices.get(model)
        cost = ((input_tokens * prices[0] + output_tokens * prices[1]) / 1_000_000) if prices and input_tokens is not None and output_tokens is not None else None
        duration_ms = (time.perf_counter() - start) * 1000
        if _run_id.get():
            add_usage(_run_id.get(), _session_id.get(), operation, model, status, input_tokens, output_tokens, cost, duration_ms)
        event("llm.call", status=status, duration_ms=duration_ms, details={"operation": operation, "model": model, "input_tokens": input_tokens, "output_tokens": output_tokens, "estimated_cost_usd": cost})


URL_MODEL = os.getenv("GROQ_URL_MODEL", "openai/gpt-oss-20b")
PLAN_MODEL = os.getenv("GROQ_PLAN_MODEL", "openai/gpt-oss-120b")
ANSWER_MODEL = os.getenv("GROQ_ANSWER_MODEL", "openai/gpt-oss-120b")
SUMMARY_MODEL = os.getenv("GROQ_SUMMARY_MODEL", "openai/gpt-oss-20b")
