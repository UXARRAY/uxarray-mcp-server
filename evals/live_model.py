"""Live-model adapter for the eval harnesses.

The scripted adapters in ``evals/multi_turn/scripted.py`` bracket the
achievable score range and keep the harness runnable offline. This module
closes the remaining gap: it drives a real language model through the same
adapter boundary, so the reported numbers describe model behavior rather
than a stand-in for it.

Any OpenAI-compatible endpoint works. Configure with:

    EVAL_MODEL_BASE_URL   default http://localhost:44445/v1
    EVAL_MODEL_API_KEY    default $ARGO_API_KEY, else "none"
    EVAL_MODEL_ID         required, e.g. argo:gpt-4o
    EVAL_MODEL_TEMP       default 0.0

Usage:

    EVAL_MODEL_ID=argo:gpt-4o uv run python -m evals.multi_turn.run \
        --adapter evals.live_model:adapter --model-id argo:gpt-4o
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

_DEFAULT_BASE = "http://localhost:44445/v1"
_TIMEOUT_S = 120
_RETRIES = 4


class LiveModelError(RuntimeError):
    """Raised when the endpoint cannot be reached or returns no choice."""


def _config() -> tuple[str, str, str, float]:
    base = os.environ.get("EVAL_MODEL_BASE_URL", _DEFAULT_BASE).rstrip("/")
    key = (
        os.environ.get("EVAL_MODEL_API_KEY") or os.environ.get("ARGO_API_KEY") or "none"
    )
    model = os.environ.get("EVAL_MODEL_ID", "")
    if not model:
        raise LiveModelError("EVAL_MODEL_ID is not set")
    temp = float(os.environ.get("EVAL_MODEL_TEMP", "0.0"))
    return base, key, model, temp


def _to_openai_tools(catalog: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Expose the harness catalog as OpenAI function tools.

    The harness catalog documents arguments in prose rather than as a
    schema, so the parameter object stays open. That is deliberate: this
    eval asks whether a model carries opaque handles between calls, and
    constraining the arguments here would do that work for it.
    """
    tools = []
    for entry in catalog:
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": entry["name"],
                    "description": entry["description"],
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "additionalProperties": True,
                    },
                },
            }
        )
    return tools


def _post_once(url: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    """One request. Returns the decoded body even for HTTP error statuses."""
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:  # 4xx/5xx carry a JSON body
        raw = exc.read().decode("utf-8", "replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"error": {"message": raw[:500], "status": exc.code}}


def _rejects_temperature(response: dict[str, Any]) -> bool:
    """True when the provider refused the request only over ``temperature``.

    Reasoning-tuned deployments pin sampling to their default and answer a
    pinned temperature with a 400 rather than ignoring it. That is a dialect
    difference, not a model behavior, so it must not be scored as a failure.
    """
    error = response.get("error")
    if not isinstance(error, dict):
        return False
    text = str(error.get("message", ""))
    return "temperature" in text and (
        "unsupported" in text.lower() or "does not support" in text.lower()
    )


def _post(url: str, payload: dict[str, Any], key: str) -> dict[str, Any]:
    last: Exception | str | None = None
    attempted_without_temperature = False
    for attempt in range(_RETRIES):
        try:
            response = _post_once(url, payload, key)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(2**attempt)
            continue
        if "error" not in response:
            return response
        if _rejects_temperature(response) and not attempted_without_temperature:
            payload = {k: v for k, v in payload.items() if k != "temperature"}
            attempted_without_temperature = True
            continue
        last = str(response.get("error"))[:300]
        time.sleep(2**attempt)
    raise LiveModelError(f"request failed after {_RETRIES} attempts: {last}")


def adapter(
    messages: list[dict[str, Any]], catalog: list[dict[str, str]]
) -> dict[str, Any]:
    """Return ``{"text": str, "tool_calls": [{"name", "arguments"}]}``."""
    base, key, model, temp = _config()

    # The harness speaks a reduced message dialect; normalize tool turns to
    # the plain user role so any provider accepts the transcript without
    # requiring matched tool_call_id bookkeeping.
    wire: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        content = str(message.get("content", ""))
        if role == "tool":
            wire.append({"role": "user", "content": f"[tool result]\n{content}"})
            continue
        if not content.strip():
            # A turn whose only content was a tool call arrives here empty.
            # Some providers reject an empty part outright rather than
            # ignoring it, which would score a dialect difference as a
            # model failure, so carry the turn with an explicit marker.
            if role == "assistant":
                content = "(issued a tool call)"
            else:
                continue
        wire.append({"role": role, "content": content})
    if not wire:
        wire = [{"role": "user", "content": "Continue."}]

    response = _post(
        f"{base}/chat/completions",
        {
            "model": model,
            "messages": wire,
            "tools": _to_openai_tools(catalog),
            "temperature": temp,
        },
        key,
    )

    choices = response.get("choices") or []
    if not choices:
        raise LiveModelError(f"no choice returned: {str(response)[:200]}")
    message = choices[0].get("message", {}) or {}
    text = str(message.get("content") or "")

    calls: list[dict[str, Any]] = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function", {}) or {}
        name = function.get("name")
        if not name:
            continue
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append({"name": name, "arguments": arguments})

    # A model that stops calling tools and only writes prose has decided it
    # is done; the harness needs that expressed as the terminal call.
    if not calls and text:
        calls = [{"name": "finish", "arguments": {}}]

    return {"text": text, "tool_calls": calls}
