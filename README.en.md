# craft-process MCP Field Guide

English · [中文](README.md)

Deployment notes, interface contracts, workflow gates and fixes for an MCP server that turns 2D drawings into structured features and template-driven process cards. Everything here comes from running the service against real drawings. The repository contains **no server source code, no company names, no drawing numbers and no real host addresses**.

## What it is

The service is a Streamable HTTP MCP endpoint exposing a set of `craft_*` tools: create a job, review extracted features, match and select a template, fill parameter slots, generate and export a process card. To a client it is just an MCP server. On the server side it is two layers: an MCP shell and a business backend.

```
MCP client ──(Streamable HTTP)──> MCP shell (FastAPI/uvicorn)
                                        │  HTTP
                                        ▼
                                  backend (Flask/Werkzeug)
                                  /api/jobs, /workbench, /feature-review ...
```

The important part: the shell and the backend are separate processes and may not share a host or a network namespace. Most "cannot connect" failures happen at that hop, not in the MCP configuration. See [docs/01-architecture.md](docs/01-architecture.md).

## Quick start

```json
{
  "mcpServers": {
    "craft-process": {
      "type": "http",
      "url": "http://<mcp-host>:8764/mcp"
    }
  }
}
```

The full path, including multipart uploads and the acceptance criteria for each step, is in [docs/02-quickstart.md](docs/02-quickstart.md).

**If you are an agent that will call this service**, skip that and read [docs/05-agent-playbook.md](docs/05-agent-playbook.md) instead: actions, acceptance checks and prohibitions only. The host is not in this repository; the playbook's section 0 says where to read it from.

## Symptom index

| Symptom | Check first |
| --- | --- |
| Handshake works, tool calls fail to connect | the shell-to-backend hop |
| "File not found" from a tool | paths resolve on the shell host |
| 409 on a write | stale `revision`, re-read the workbench |
| 409 when generating the card | candidates are not a selection |
| Template selection times out but state moved | client timeout, server already committed |
| Export produces nothing | file written inside the shell container |

Detailed triage in [docs/04-troubleshooting.md](docs/04-troubleshooting.md).

## Fixes

Nine notes, ordered by risk, with a suggested sequence in [docs/06-optimization-plan.md](docs/06-optimization-plan.md):

1. [Configurable backend base URL](patches/01-api-base-url.md) — deployment only, no data change.
2. [Merge semantics for feature review](patches/02-feature-review-payload.md) — stop wiping the feature table.
3. [`create_job` accepts file content](patches/03-file-content-input.md) — decouple client from the backend filesystem.
4. [Timeouts and export](patches/04-timeout-and-export.md) — long tasks and artifact delivery.
5. [Draft process card tools](patches/05-draft-process-card-tools.md) — the review step the UI has and MCP lacks.
6. [`next_action` tool](patches/06-next-action-tool.md) — put the next step in the protocol.
7. [Job state consistency](patches/07-state-consistency.md) — stop reading and writing the wrong job.
8. [Slot value authority](patches/08-slot-value-authority.md) — confirmed values outrank derived ones.
9. [Generation semantics and counts](patches/09-generate-semantics.md) — no-op generate, rejected counting, export type.
10. [Backend address discovery](patches/10-backend-address-discovery.md) — let `craft_health` name the backend instead of hunting ports.

A complete real run, including the revision timeline, is recorded in [docs/07-field-notes.md](docs/07-field-notes.md).

## Workflow and gates

Human confirmation is a hard gate in this service, not an option. The three gates, the provenance rules for parameter values and the business red lines are in [docs/03-workflow-and-gates.md](docs/03-workflow-and-gates.md).

## Layout

```
README.md / README.en.md   this file and the Chinese version
LICENSE / NOTICE           Apache-2.0
docs/01-architecture.md    two-layer architecture and layered triage
docs/02-quickstart.md      connect, upload, run
docs/03-workflow-and-gates.md  gates, constraints, red lines
docs/04-troubleshooting.md symptom-driven runbook
docs/05-agent-playbook.md  ten-step protocol for agents
docs/06-optimization-plan.md  phased plan with acceptance criteria
docs/07-field-notes.md        one real run, with revision timeline
docs/08-endpoint-discovery.md finding the backend without port scans
docs/09-asking-humans.md   question formats for text-only harnesses
docs/10-harness-interaction.md  one question file, rendered per harness
mcp.example.json           client config template (placeholder host)
tools/craft_discover.py    verify candidate endpoints by service fingerprint
tools/craft_upload.py      upload with a long timeout, a job ledger, hash dedupe
tools/review_sheet.py      turn a workbench into a clickable review sheet
tools/ask.py               neutral questions -> md / html / json, and parse replies
patches/                   ten fix and improvement proposals
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). This is an unofficial field guide with no affiliation to any vendor, product or service.
