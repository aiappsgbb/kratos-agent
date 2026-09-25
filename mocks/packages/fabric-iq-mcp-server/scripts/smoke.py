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
    print("== fabric-iq smoke ==")

    r = run(("fabric_iq_list_lines", {"site_id": "PLANT-RIVERTON"}))
    payload = text_of(r.get(2))
    results.append(check("fabric_iq_list_lines lists Riverton lines", isinstance(payload, dict) and payload.get("total", 0) >= 2, str(payload)[:140] if payload else "empty"))

    r = run(("fabric_iq_get_oee", {"line_id": "LINE-2-PACKAGING", "date_from": "2026-09-12", "date_to": "2026-09-13"}))
    payload = text_of(r.get(2))
    results.append(check("fabric_iq_get_oee returns degraded packaging OEE", isinstance(payload, dict) and payload.get("total", 0) >= 2, str(payload)[:140] if payload else "empty"))

    r = run(("fabric_iq_get_asset_status", {"asset_id": "ASSET-2-CASE-PACKER"}))
    payload = text_of(r.get(2))
    results.append(check("fabric_iq_get_asset_status finds the degraded packer", isinstance(payload, dict) and payload.get("asset", {}).get("id") == "ASSET-2-CASE-PACKER", str(payload)[:140] if payload else "empty"))

    r = run(("fabric_iq_get_telemetry", {"asset_id": "ASSET-2-CASE-PACKER", "limit": 3}))
    payload = text_of(r.get(2))
    results.append(check("fabric_iq_get_telemetry returns packer readings", isinstance(payload, dict) and payload.get("total", 0) >= 3, str(payload)[:140] if payload else "empty"))

    r = run(("fabric_iq_list_alarms", {"site_id": "PLANT-RIVERTON", "status": "Active"}))
    payload = text_of(r.get(2))
    results.append(check("fabric_iq_list_alarms returns active Riverton alarms", isinstance(payload, dict) and payload.get("total", 0) >= 1, str(payload)[:140] if payload else "empty"))

    print()
    passed = sum(1 for ok in results if ok)
    total = len(results)
    print(f"== SUMMARY ==  {passed}/{total} passed")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
