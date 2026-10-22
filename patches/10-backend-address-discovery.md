# Patch 10: let the service disclose its own backend

Risk: low. Read-only information disclosure to the same callers who already use the service.

## Problem

The MCP shell knows the backend base URL — it must, in order to call it — but never tells the caller. `craft_health` returns a service name and `ok`. Everything that has to bypass the shell (multipart upload, artifact export) then depends on a URL the caller cannot obtain, so people scan ports and find unrelated services on the way.

This is the cheapest fix in the whole plan: the information already exists in the shell's environment.

## Change

`craft_health` returns the backend it is configured to use:

```json
{
  "ok": true,
  "data": {
    "service": "dica-2d-feature-extraction",
    "status": "ok",
    "backend_url": "http://172.17.0.1:5199",
    "backend_reachable": true,
    "tool_version": "1.0.0",
    "build": "2026-10-21"
  }
}
```

`backend_url` is the address the shell uses, not necessarily one the caller can reach. Say so in the field name or the docs (`backend_url` plus `backend_reachable`) rather than implying it is universally routable. A caller on the same network gets a usable value; a caller elsewhere learns that a proxy or a public address is involved and can ask.

Add `tool_version` and `build` while you are there. Builds differ in field shapes (`replacement` vs `decision.candidates`, `selected_template_id` null or not), and callers currently have no way to tell which one they are talking to.

## Optional: a well-known document

For discovery without MCP at all:

```
GET /.well-known/craft-process.json
{
  "service": "dica-2d-feature-extraction",
  "mcp": "http://host:8764/mcp",
  "backend": "http://host:5199",
  "version": "1.0.0"
}
```

Serve it from the shell or the backend. It makes onboarding a single fetch and gives load balancers something to health-check.

## Security note

The backend URL is already inferable from the shell's error messages when it is misconfigured, so disclosing it deliberately is not a new leak. If the service is exposed publicly, consider whether the backend address should be public too; exposing the shell without auth is the larger problem, and [patch 07](07-state-consistency.md) plus deployment-side auth is where that gets fixed.

## Acceptance

`craft_health` on a misconfigured shell reports the URL it tried and `backend_reachable: false`, which turns the most common deployment failure into a one-line diagnosis instead of a port hunt.

A caller with only the MCP URL can complete upload and export without asking anyone.
