# Architecture

## Two layers, one endpoint

Clients see one URL. Internally there are two services with different responsibilities and failure modes.

```
┌────────────────┐   Streamable HTTP   ┌──────────────────────┐   plain HTTP   ┌─────────────────────────┐
│ MCP client     │ ──────────────────> │ MCP shell            │ ─────────────> │ backend                 │
│ (agent, CLI)   │ <────────────────── │ FastAPI + uvicorn    │ <───────────── │ Flask/Werkzeug          │
└────────────────┘   SSE / JSON-RPC    │ tool schema,         │                │ jobs, extraction,       │
                                       │ validation, mapping  │                │ templates, process card │
                                       └──────────────────────┘                └─────────────────────────┘
```

The shell owns the MCP protocol: `initialize`, `tools/list`, `tools/call`, and the JSON-RPC envelope. It also validates arguments and maps tool calls onto backend REST endpoints. It does **not** do extraction, template matching or card generation; those are backend concerns.

The backend owns state: jobs, extracted features, the workbench, template candidates and selections, parameter slots, and the generated card. It is a Flask/Werkzeug application whose root path serves the web workbench.

## Where state lives

| State | Owner | Read via |
| --- | --- | --- |
| Job status and progress | backend | `GET /api/jobs/{id}` |
| Extracted features, review decisions | backend | `GET /api/jobs/{id}/workbench` |
| Template candidates | backend | workbench / `template-match` |
| Selected template | backend | workbench `replacement` / `decision` |
| Parameter slots | backend | workbench |
| Generated card | backend | `GET /api/jobs/{id}/process-card` |

Two consequences matter in practice.

The workbench is the single source of truth. Tool responses are convenient projections of it. When any write is rejected, re-read the workbench rather than retrying the same payload.

The MCP shell is stateless with respect to business data. Restarting or losing the shell does not lose jobs; restarting the backend does.

## Revisions

Every write carries a `revision`. The server compares it with the current workbench revision and returns `409` on mismatch. This is optimistic concurrency, not authentication.

Some deployments make `revision` optional and auto-read the latest value, echoing `revision_source: "auto"`. That is convenient but hides concurrent edits: two clients can both succeed while one silently overwrites the other's decisions. Pass the revision you actually read.

## Failure layering

When a tool call fails, locate the break before changing anything.

| Layer | Probe | Healthy signal |
| --- | --- | --- |
| Network to shell | TCP connect to the MCP port | connection accepted |
| MCP protocol | `initialize` request | `200` with `mcp-session-id` |
| Tool discovery | `tools/list` | expected tool count |
| Shell → backend | invoke a read-only tool, or hit the backend health path | `200` JSON |
| Backend business | call the REST endpoint the tool maps to | expected payload |

A shell that completes `initialize` and returns tools is a working MCP server. If tool calls then fail with a connection error, the break is below the MCP layer and client-side configuration changes will not help.

## Network topology traps

Two deployment shapes recur.

**Same host, same namespace.** The shell can reach the backend at loopback. Simple, but only true when both run on the same machine outside containers.

**Shell in a container, backend on the host.** Loopback inside the container is the container itself, not the host. A configured base URL of `127.0.0.1` will fail forever, while the backend's public address works from anywhere else. The fix is to point the shell at an address that is routable from inside its namespace — commonly the container bridge gateway — and to recreate the container so the environment is re-injected. `restart` alone does not reload environment variables.

Common signals of this shape: backend health returns `200` from your machine, the MCP handshake succeeds, every business tool returns a connection error, and the error text contains a loopback address.

## Health endpoints are not standardised

Do not assume `/health` exists on the MCP port. Some builds expose only `/mcp` and return `404` at the root. Probe the MCP endpoint with `initialize` instead; that is the authoritative liveness check for the shell. The backend's own health path is separate and usually does exist.
