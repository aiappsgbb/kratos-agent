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
    print("== foundry-iq smoke ==")

    r = run(("foundry_iq_search_knowledge", {"query": "label registration", "plant_id": "PLANT-RIVERTON", "limit": 2}))
    payload = text_of(r.get(2))
    results.append(check("foundry_iq_search_knowledge finds Riverton packaging docs", isinstance(payload, dict) and payload.get("total", 0) >= 1, str(payload)[:140] if payload else "empty"))

    r = run(("foundry_iq_get_document", {"source_id": "SRC-RIVERTON-101"}))
    payload = text_of(r.get(2))
    results.append(check("foundry_iq_get_document returns Riverton citations", isinstance(payload, dict) and payload.get("source_id") == "SRC-RIVERTON-101" and len(payload.get("citations", [])) >= 1, str(payload)[:140] if payload else "empty"))

    print()
    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"== SUMMARY ==  {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
