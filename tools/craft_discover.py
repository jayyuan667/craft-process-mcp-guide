#!/usr/bin/env python3
"""Discover the craft-process backend base URL without port scanning.

The MCP shell knows the backend; callers usually do not. This asks the shell
(craft_health), then validates a small explicit candidate list against the
service name the shell reports, so unrelated services on neighbouring ports
are rejected instead of mistaken for the backend.

Standard library only. Works on Windows, macOS and Linux.

Usage:
    python craft_discover.py --mcp http://1.2.3.4:8764/mcp
    python craft_discover.py --mcp ... --ports 5199,5200 --save endpoints.json

Exit codes: 0 found, 2 not found, 1 usage/connection error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "craft-discover", "version": "1"},
    },
}
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _decode(body: bytes) -> str:
    text = body.decode("utf-8", "replace")
    if text.lstrip().startswith("{"):
        return text
    # Streamable HTTP may answer as SSE; concatenate data lines.
    parts = [line[5:].lstrip() for line in text.splitlines() if line.startswith("data:")]
    return "\n".join(parts) if parts else text


def post(url: str, payload: dict, session: str | None = None, timeout: int = 15):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=dict(HEADERS), method="POST")
    if session:
        req.add_header("mcp-session-id", session)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.headers.get("mcp-session-id") or session, json.loads(_decode(resp.read()))


def mcp_health(mcp_url: str) -> tuple[str | None, dict]:
    session, _ = post(mcp_url, INIT)
    _, reply = post(
        mcp_url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": "craft_health", "arguments": {}}},
        session,
    )
    result = reply.get("result") or {}
    texts = [c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)]
    blob = "\n".join(texts)
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        payload = {"raw": blob}
    service = None
    for candidate in (payload.get("data") or {}, payload):
        if isinstance(candidate, dict) and isinstance(candidate.get("service"), str):
            service = candidate["service"]
            break
    if service is None:
        m = re.search(r'"service"\s*:\s*"([^"]+)"', blob)
        service = m.group(1) if m else None
    backend = None
    for candidate in (payload.get("data") or {}, payload):
        if isinstance(candidate, dict):
            for key in ("backend_url", "backend", "api_base_url", "service_url"):
                if isinstance(candidate.get(key), str):
                    backend = candidate[key]
                    break
        if backend:
            break
    return service, {"payload": payload, "reported_backend": backend}


def probe_health(base: str, timeout: int = 3) -> tuple[str | None, str]:
    url = base.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - report, do not crash
        return None, type(exc).__name__
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return None, "not JSON (wrong service?)"
    service = data.get("service") if isinstance(data, dict) else None
    return service, "json"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mcp", required=True, help="MCP endpoint, e.g. http://host:8764/mcp")
    ap.add_argument("--ports", default="5199", help="comma-separated candidate ports (default 5199)")
    ap.add_argument("--save", help="write the discovered endpoints to this JSON file")
    args = ap.parse_args()

    try:
        service, meta = mcp_health(args.mcp)
    except Exception as exc:  # noqa: BLE001
        print(f"MCP shell unreachable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"MCP shell : {args.mcp}")
    print(f"service   : {service or 'unknown (craft_health returned no service name)'}")
    if meta["reported_backend"]:
        print(f"reported  : {meta['reported_backend']} (from craft_health)")

    host = re.sub(r"^[\w+.-]+://", "", args.mcp).split("/")[0].split(":")[0]
    scheme = "https" if args.mcp.startswith("https://") else "http"

    candidates: list[tuple[str, str]] = []
    if os.environ.get("CRAFT_BACKEND_URL"):
        candidates.append((os.environ["CRAFT_BACKEND_URL"].rstrip("/"), "env CRAFT_BACKEND_URL"))
    if meta["reported_backend"]:
        candidates.append((meta["reported_backend"].rstrip("/"), "craft_health"))
    for port in [p.strip() for p in args.ports.split(",") if p.strip()]:
        candidates.append((f"{scheme}://{host}:{port}", f"host + port {port}"))

    seen: set[str] = set()
    for base, why in candidates:
        if base in seen:
            continue
        seen.add(base)
        found, note = probe_health(base)
        if found and service and found == service:
            print(f"backend   : {base}  [verified via {why}; /health service matches]")
            if args.save:
                with open(args.save, "w", encoding="utf-8") as fh:
                    json.dump({"mcp": args.mcp, "backend": base, "service": service}, fh, indent=2)
                print(f"saved     : {args.save}")
            return 0
        if found:
            print(f"  skip    : {base} [{why}] -> service={found!r}, not the one we need")
        else:
            print(f"  skip    : {base} [{why}] -> {note}")

    print("\nNot found. Ask the deployment owner for the backend base URL, then set:")
    print("  export CRAFT_BACKEND_URL=http://<backend-host>:<port>")
    print("Do not widen the port list into a scan; neighbouring ports belong to other services.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
