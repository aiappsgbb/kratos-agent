"""Tests for hosted-agent invocation body parsing.

``azd ai agent invoke "msg"`` POSTs the raw message as ``text/plain`` — NOT
JSON. The hosted agent must accept that, as well as JSON objects (the backend
proxy path), bare JSON strings, and empty keep-alive pings. The body-coercion
logic lives in a dependency-free helper so it can be unit-tested without
importing the full agentserver runtime.
"""

from __future__ import annotations

from app.hosted_agent_invoke import parse_invoke_payload


def test_json_object_is_returned_as_is():
    raw = b'{"message": "hi there", "useCase": "finance-close"}'
    assert parse_invoke_payload(raw) == {"message": "hi there", "useCase": "finance-close"}


def test_plain_text_becomes_message():
    # This is what `azd ai agent invoke "hello world"` sends (text/plain).
    assert parse_invoke_payload(b"hello world") == {"message": "hello world"}


def test_bare_json_string_becomes_message():
    # A JSON-encoded bare string (e.g. body == '"hello"').
    assert parse_invoke_payload(b'"hello"') == {"message": "hello"}


def test_empty_body_is_warmup():
    assert parse_invoke_payload(b"") == {"warmup": True}


def test_whitespace_only_body_is_warmup():
    assert parse_invoke_payload(b"   \n\t ") == {"warmup": True}


def test_explicit_warmup_object_is_preserved():
    assert parse_invoke_payload(b'{"warmup": true}') == {"warmup": True}


def test_json_array_falls_back_to_text_message():
    # Non-object / non-string JSON scalars & arrays are treated as the message.
    assert parse_invoke_payload(b"[1, 2, 3]") == {"message": "[1, 2, 3]"}


def test_invalid_utf8_does_not_raise():
    # Should degrade gracefully rather than 500 on a bad byte sequence.
    result = parse_invoke_payload(b"\xff\xfe bad bytes")
    assert "message" in result
