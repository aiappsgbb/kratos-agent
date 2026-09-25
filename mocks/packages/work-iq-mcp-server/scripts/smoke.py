#!/usr/bin/env python3
import json
import subprocess
import sys

SERVER = "node dist/server.js"


def make_calls(*calls):
    out = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0.0.1"}}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}),
    ]
    for i, (name, args) in enumerate(calls, start=2):
        out.append(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}))
    return "\n".join(out) + "\n"


def run(*calls):
    payload = make_calls(*calls)
    p = subprocess.run(SERVER.split(), input=payload, capture_output=True, text=True, timeout=10)
    out = {}
    for line in p.stdout.splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if "id" in item and item["id"] is not None:
            out[item["id"]] = item
    return out


def text_of(resp):
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
    print("== work-iq smoke ==")

    r = run(("work_iq_search_people", {"query": "Jordan", "limit": 5}))
    payload = text_of(r.get(2))
    results.append(check("work_iq_search_people finds the Aster Works supervisor", isinstance(payload, dict) and payload.get("total", 0) >= 1, str(payload)[:120] if payload else "empty"))

    r = run(("work_iq_get_person", {"person_id": "PERSON-100"}))
    payload = text_of(r.get(2))
    results.append(check("work_iq_get_person resolves Jordan Lee", isinstance(payload, dict) and payload.get("id") == "PERSON-100", str(payload)[:120] if payload else "empty"))

    r = run(("work_iq_find_availability", {"person_ids": ["PERSON-102", "PERSON-103"], "date": "2026-09-15"}))
    payload = text_of(r.get(2))
    results.append(check("work_iq_find_availability returns a shared maintenance and quality slot", isinstance(payload, dict) and len(payload.get("common_available_slots", [])) >= 1, str(payload)[:160] if payload else "empty"))

    meeting = {"title": "Riverton packaging recovery review", "date": "2026-09-15", "time": "15:30", "duration_minutes": 30, "organizer_id": "PERSON-100", "attendees": ["PERSON-102", "PERSON-103"], "agenda": "Review label drift and action plan."}
    prep = run(("work_iq_prepare_meeting", meeting))
    prep_payload = text_of(prep.get(2))
    token = prep_payload.get("confirmation_token") if isinstance(prep_payload, dict) else None
    results.append(check("work_iq_prepare_meeting produces a confirmation token", isinstance(prep_payload, dict) and bool(token), str(prep_payload)[:160] if prep_payload else "empty"))

    r = run(("work_iq_create_meeting", {**meeting, "confirmation_token": token or "BAD", "confirm": False}))
    err = text_of(r.get(2))
    results.append(check("work_iq_create_meeting rejects unconfirmed requests", isinstance(err, dict) and err.get("error") == "confirmation_required", str(err)[:160] if err else "empty"))

    r = run(("work_iq_create_meeting", {**meeting, "confirmation_token": token, "confirm": True}))
    payload = text_of(r.get(2))
    results.append(check("work_iq_create_meeting accepts a valid confirmation token", isinstance(payload, dict) and payload.get("meeting", {}).get("status") == "scheduled", str(payload)[:160] if payload else "empty"))

    print()
    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"== SUMMARY ==  {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
