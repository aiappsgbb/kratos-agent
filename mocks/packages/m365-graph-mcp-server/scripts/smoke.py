#!/usr/bin/env python3
"""Smoke test the m365-graph-mcp-server over stdio JSON-RPC.

Runs a battery of read + write tool calls and prints PASS/FAIL per check.
"""
import json
import subprocess
import sys

SERVER = "node packages/m365-graph-mcp-server/dist/server.js"


def make_calls(*calls):
    """Build the JSON-RPC stream: init, initialized, then each tools/call."""
    out = [
        json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "smoke", "version": "0.0.1"}},
        }),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
    ]
    for i, (name, args) in enumerate(calls, start=2):
        out.append(json.dumps({
            "jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }))
    return "\n".join(out) + "\n"


def run(*calls):
    payload = make_calls(*calls)
    p = subprocess.run(
        SERVER.split(), input=payload, capture_output=True, text=True, timeout=10,
    )
    responses = {}
    for line in p.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if "id" in d and d["id"] is not None:
            responses[d["id"]] = d
    return responses


def text_of(resp):
    """Extract the JSON-decoded payload from a tools/call response."""
    if not resp:
        return None
    res = resp.get("result")
    if not res:
        return resp.get("error")
    blocks = res.get("content") or []
    if not blocks:
        return None
    try:
        return json.loads(blocks[0]["text"])
    except Exception:
        return blocks[0].get("text")


def check(label, ok, detail=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f"  — {detail}" if detail else ""))
    return ok


def main():
    results = []

    # ── READS ────────────────────────────────────────────────────────────
    print("\n== READS ==")

    r = run(("m365_list_users", {"department": "Engineering"}))
    payload = text_of(r.get(2))
    eng_count = payload["total"] if payload else 0
    results.append(check(
        "m365_list_users department=Engineering returns >= 8",
        eng_count >= 8, f"got {eng_count}",
    ))

    r = run(("m365_get_user", {"selector": "EMP-1011"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_get_user EMP-1011 -> Aisha Okonkwo",
        bool(p) and p.get("displayName") == "Aisha Okonkwo",
        p.get("displayName", "<missing>") if isinstance(p, dict) else str(p),
    ))

    r = run(("m365_get_user", {"selector": "aisha.okonkwo@olympus.example.com"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_get_user by mail -> same user",
        bool(p) and p.get("id") == "EMP-1011",
    ))

    r = run(("m365_get_user_presence", {"selector": "EMP-2003"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_get_user_presence EMP-2003 -> OOO enabled with handover msg",
        bool(p) and p["ooo"]["enabled"] is True and "parental leave" in (p["ooo"]["message"] or "").lower(),
    ))

    r = run(("m365_search_messages", {"mailbox": "EMP-1011", "flagged_only": True}))
    p = text_of(r.get(2))
    flagged_count = p["total"] if p else 0
    results.append(check(
        "m365_search_messages mailbox=Aisha flagged_only -> >=3",
        flagged_count >= 3, f"got {flagged_count}",
    ))

    r = run(("m365_search_messages", {"mailbox": "EMP-1011", "query": "Sentinel"}))
    p = text_of(r.get(2))
    sentinel_count = p["total"] if p else 0
    results.append(check(
        "m365_search_messages query=Sentinel -> >=2 hits",
        sentinel_count >= 2, f"got {sentinel_count}",
    ))

    r = run(("m365_get_thread", {"conversation_id": "CONV-301"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_get_thread CONV-301 -> 3 messages in chronological order",
        bool(p) and p["total"] == 3
        and p["messages"][0]["id"] == "MSG-30001"
        and p["messages"][-1]["id"] == "MSG-30003",
    ))

    r = run(("m365_list_events", {
        "mailbox": "EMP-1011", "from_date": "2026-06-05", "to_date": "2026-06-08",
    }))
    p = text_of(r.get(2))
    evt_count = p["total"] if p else 0
    results.append(check(
        "m365_list_events Aisha 5-8 Jun -> >=3",
        evt_count >= 3, f"got {evt_count}",
    ))

    r = run(("m365_search_files", {"query": "variance"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_search_files query=variance -> 1 hit",
        bool(p) and p["total"] >= 1 and any("variance" in f["name"].lower() for f in p["files"]),
    ))

    r = run(("m365_list_chats", {"user": "EMP-1011"}))
    p = text_of(r.get(2))
    results.append(check(
        "m365_list_chats Aisha -> >=3 chats",
        bool(p) and p["total"] >= 3,
    ))

    r = run(("m365_search_chat_messages", {
        "user": "EMP-2001", "mentioned_only": True,
    }))
    p = text_of(r.get(2))
    results.append(check(
        "m365_search_chat_messages mentioned_only=Theo -> >=1 hit",
        bool(p) and p["total"] >= 1,
    ))

    # ── WRITES ──────────────────────────────────────────────────────────
    print("\n== WRITES ==")

    # Draft round trip — the in-memory store is per-process. The MCP SDK over
    # stdio does not strictly serialise tools/call, so we can't chain
    # draft -> send in a single batch and assume the send sees the new draft.
    # In a real agent the LLM always waits for the draft response before issuing
    # the send, so this is not a server bug; just a smoke-test limitation.
    # Here we only assert draft creation; the happy-path send is exercised
    # via the agent end-to-end test once the persona is wired up.
    draft_call = ("m365_draft_message", {
        "from": "EMP-1011",
        "to": ["hiroshi.tanaka@olympus.example.com"],
        "cc": ["sofia.martinez@olympus.example.com"],
        "subject": "Re: May close — CC-0011 variance commentary",
        "body": "Hi Hiroshi,\n\nCommentary attached as discussed...",
    })
    r = run(draft_call)
    draft = text_of(r.get(2))
    draft_id = draft and draft.get("draft", {}).get("id")
    results.append(check(
        "m365_draft_message -> Draft created in Drafts folder",
        bool(draft_id) and draft["draft"]["folder"] == "Drafts",
        draft_id or str(draft)[:120],
    ))

    # Sending a non-Draft must fail (this is the negative case we *can* run
    # cleanly because it doesn't depend on a prior write).
    r3 = run(("m365_send_message", {"message_id": "MSG-30001"}))
    err = text_of(r3.get(2))
    results.append(check(
        "m365_send_message on non-Draft is rejected with validation_error",
        isinstance(err, dict) and err.get("error") == "validation_error",
        str(err)[:120],
    ))

    # Sending an unknown id is also a validation/not-found error.
    r4 = run(("m365_send_message", {"message_id": "MSG-99999"}))
    err = text_of(r4.get(2))
    results.append(check(
        "m365_send_message on unknown id -> not_found",
        isinstance(err, dict) and err.get("error") == "not_found",
        str(err)[:120],
    ))

    # Create event
    r = run(("m365_create_event", {
        "organizer": "EMP-1011",
        "subject": "Variance commentary review",
        "attendees": [{"email": "hiroshi.tanaka@olympus.example.com"}],
        "start_iso": "2026-06-09T15:00:00",
        "end_iso":   "2026-06-09T15:30:00",
        "is_online_meeting": True,
        "body_preview": "30-min review of CC-0011 variance commentary before Sofia's pack.",
    }))
    evt = text_of(r.get(2))
    results.append(check(
        "m365_create_event -> event booked with attendee response=none",
        bool(evt) and evt["event"]["subject"] == "Variance commentary review"
        and any(a["status"]["response"] == "none" for a in evt["event"]["attendees"]),
    ))

    # End-of-day end
    print()
    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"== SUMMARY ==  {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
