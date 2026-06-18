"""Coerce hosted-agent invocation request bodies into a normalized dict.

The Foundry hosted-agent receives invocations through several paths, each of
which frames the request body differently:

* ``azd ai agent invoke "msg"`` — posts the raw message as ``text/plain``,
  **not** JSON. Naively calling ``request.json()`` on this raises and the agent
  used to reject it with a 400, breaking the primary CLI test path.
* The Kratos backend proxy — posts a JSON object
  (``{"message": ..., "useCase": ..., "conversationId": ...}``).
* Platform keep-alive — posts ``{"warmup": true}`` (or an empty body) to reset
  the idle timer without invoking the model.

This helper is intentionally dependency-free (stdlib ``json`` only) so it can be
unit-tested without importing the agentserver runtime.
"""

from __future__ import annotations

import json
from typing import Any


def parse_invoke_payload(raw: bytes) -> dict[str, Any]:
    """Normalize a raw invocation body into a dict.

    Returns one of:
      * the JSON object as-is, when the body is a JSON object;
      * ``{"message": <text>}`` for a JSON string, plain text, or any other
        non-object JSON value (arrays/numbers are stringified back to text);
      * ``{"warmup": True}`` for an empty or whitespace-only body.
    """
    text = raw.decode("utf-8", "replace").strip() if raw else ""
    if not text:
        return {"warmup": True}

    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        # Plain text (e.g. `azd ai agent invoke "hello"`).
        return {"message": text}

    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        return {"message": parsed}

    # Any other JSON scalar/array: treat the original text as the message.
    return {"message": text}
