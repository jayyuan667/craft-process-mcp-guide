# craft-process MCP Field Guide

English summary · [中文](README.md)

Deployment notes, interface contracts, workflow gates and fixes for an MCP server that turns 2D drawings into structured features and template-driven process cards. Everything here comes from running the service against real drawings. The repository contains **no server source code, no company names, no drawing numbers and no real host addresses**.

**This build has no authentication.** It is meant for a local machine or a controlled intranet; see the security section of [docs/01-architecture.md](docs/01-architecture.md).

This page is a summary. The detailed documents are written in Chinese; `patches/` is in English. If you need the full procedure, follow the links below and read the Chinese pages — they are the source of truth. Agents can start from [llms.txt](llms.txt).

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

Two installable skills live in [skills/](skills/): `craft-process-workbench` (the normal path) and `craft-process-recovery` (triage). They bundle the CLI, so a downloaded skill only needs a backend address. Installing them does not install a service.

**If you are an agent that will call this service**, read [docs/05-agent-playbook.md](docs/05-agent-playbook.md): actions, acceptance checks and prohibitions only. The host is not in this repository; section 0 says where to read it from.

## Symptom index

| Symptom | Check first |
| --- | --- |
| Handshake works, tool calls fail to connect | the shell-to-backend hop |
| "File not found" from a tool | paths resolve on the shell host |
| `/mcp` on 5199 returns 404 | that is the backend; the shell is on 8764 (docs/04 #14) |
| 409 on a write | stale `revision`, re-read the workbench |
| 409 when generating the card | candidates are not a selection |
| Generation succeeds but no card appears | `slot-review` is what actually creates it |
| Card tolerance differs from the confirmed value | derived rules recompute at generation |
| Template selection times out but state moved | client timeout, server already committed |
| Export produces nothing | file written inside the shell container |
| Summary says no unresolved slots, detail says `partial` | gate signals disagree; stop and report |
| A valid tolerance is rejected as malformed | stop guessing formats after one grounded attempt |
| Editing the card blanks zero-hour rows | send `工时` as a string, not the number `0` |

Detailed triage is in [docs/04-troubleshooting.md](docs/04-troubleshooting.md), including the lost-`job_id` case.

## Fixes

Thirteen proposals, ordered by risk. The implementation sequence and the **current status of each one** are in [docs/06-optimization-plan.md](docs/06-optimization-plan.md):

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
11. [One validation result](patches/11-state-source-consistency.md) — gate signals must agree or fail loudly.
12. [Structured dimension fields](patches/12-structured-dimension-fields.md) — nominal and deviations as numbers, strings for display only.
13. [Saved vs confirmed vs gate-passed](patches/13-confirmation-states.md) — stop calling all three "success".

A complete real run, including the revision timeline, is recorded in [docs/07-field-notes.md](docs/07-field-notes.md).

## Workflow and gates

Human confirmation is a hard gate in this service, not an option. The three gates, the provenance rules for parameter values and the business red lines are in [docs/03-workflow-and-gates.md](docs/03-workflow-and-gates.md).

## Layout

```
README.md / README.en.md   Chinese guide and this English summary
llms.txt                   machine-readable entry point for agents
LICENSE / NOTICE           Apache-2.0
docs/01-architecture.md    two-layer architecture, security boundary and layered triage
docs/02-quickstart.md      connect, upload, run
docs/03-workflow-and-gates.md  gates, value provenance, red lines
docs/04-troubleshooting.md symptom-driven runbook (16 entries)
docs/05-agent-playbook.md  actions, criteria and prohibitions for agents
docs/06-optimization-plan.md  phased plan, acceptance criteria, patch status
docs/07-field-notes.md        one real run, with evidence and timeline
docs/08-endpoint-discovery.md finding the shell and the backend without port scans
docs/09-asking-humans.md   question formats for text-only harnesses
docs/10-harness-interaction.md  one question file, rendered per harness
docs/11-portability.md     running the flow from any harness
skills/                    two installable SKILL.md files plus install notes
skills/craft-process-workbench/scripts/  bundled CLI (craft_flow.py, craft_upload.py)
harnesses/portable-SKILL.md single-file manual for harnesses without skills
mcp.example.json           client config template (placeholder host)
tools/README.md            seven scripts, their flags and exit codes
tools/craft_flow.py        compatibility entry; implementation lives in the skill
tools/craft_upload.py      compatibility entry; implementation lives in the skill
tools/ask.py               neutral questions -> md / html / json / tui, and parse replies
tools/craft_discover.py    verify candidate endpoints by service fingerprint
tools/review_sheet.py      turn a workbench into a clickable review sheet
tools/skill_drift_check.py check whether skills/ lags behind docs/
tools/build_portable.py    generate the single-file manual from the skill
examples/                  runnable sample inputs such as questions.json
patches/                   thirteen English fix and improvement proposals
```

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE). This is an unofficial field guide with no affiliation to any vendor, product or service.
