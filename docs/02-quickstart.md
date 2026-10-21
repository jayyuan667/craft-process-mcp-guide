# Quick start

This walks the whole chain with acceptance criteria for every step. Placeholders: `<mcp-host>` for the MCP shell, `<backend-host>` for the business backend.

## 1. Connect

Client configuration for a Streamable HTTP server:

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

New sessions pick this up; an already-running client usually will not refresh its tool list.

Verify the shell without any client library:

```bash
curl -sS -X POST "http://<mcp-host>:8764/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}'
```

A `200` with an `mcp-session-id` header and a `serverInfo` payload means the shell is alive. Do not use `/health` on this port as the probe; it may not exist.

## 2. Get the file to the server

This is the step that surprises people. `craft_create_job` takes a **path**, and the path is resolved on the machine running the MCP shell — not on your laptop, not on the backend host.

Two workable patterns:

**A. The file is already visible to the shell.** Put the drawing where the shell can read it, pass that path.

**B. Upload directly to the backend.** The backend accepts multipart uploads:

```bash
curl -sS -X POST "http://<backend-host>:5199/api/jobs" \
  -F "files=@./drawing.png" \
  -F "library_key=default"
```

Response contains a `job_id`. Continue the rest of the chain through MCP using that id.

Accepted formats are PDF, PNG and JPG. Anything else is rejected at upload.

> A file path is not a file. Passing a local path to a remote tool transfers nothing; the tool simply cannot see it. If the tool reports "file not found" and you are sure the file exists, this is why. See [patches/03-file-content-input.md](../patches/03-file-content-input.md) for the contract change that removes the problem.

## 3. Wait for extraction

Extraction is asynchronous. Poll until the job reports a terminal extraction state:

```bash
curl -sS "http://<backend-host>:5199/api/jobs/<job_id>"
```

Acceptance: `status` reaches `extracted` and `progress` is `100`. Do not call create again while `queued` or `running`; you will pay for a second extraction.

Via MCP: `craft_get_job` or `craft_wait_job`.

## 4. Read the workbench

```bash
curl -sS "http://<backend-host>:5199/api/jobs/<job_id>/workbench"
```

The workbench carries `revision`, `current_stage`, `blocking_action`, per-stage status, the feature table under `review.features`, and later `replacement` (template) and slot data.

Two fields deserve attention:

`blocking_action` tells you what the server will refuse to skip. `confirm_features`, `select_template` and slot review are the usual values.

`detail=full` returns more, including extraction provenance. Behaviour differs between builds; if the response looks like a different job, check the `job_id` field in the body against the one you requested before acting on it.

## 5. Review features

Every extracted feature is a full object: id, role, role in Chinese, value, unit, confidence, status, provenance and validation reasons. The server treats `POST /feature-review` as a **whole-table replacement**, not a patch. Send only `{feature_id, decision}` and the remaining fields are lost, statuses collapse, and the workbench regresses.

Correct flow: read the full table, change only what needs changing on the objects, set `status`, and send the whole array back. Values are strings in the MCP schema; numeric values are rejected by the shell's validation. Details in [patches/02-feature-review-payload.md](../patches/02-feature-review-payload.md) and [03-workflow-and-gates.md](03-workflow-and-gates.md).

Acceptance: `counts.needs_review` drops to zero and `blocking_action` moves on.

## 6. Match and select a template

`craft_template_match` computes candidates. It is a preview. **Candidates are not a selection**, and generating a card before selecting returns `409`.

`craft_select_template` commits one candidate. On real drawings this step can take longer than a client's default timeout. A client-side timeout does not mean the server failed: re-read the workbench and check `revision` and the selected template before retrying.

Acceptance: the workbench shows a selected template in `replacement` and `blocking_action` advances.

## 7. Fill slots

`craft_update_slots` writes parameter values; `craft_review_slots` records the review decision. Values must come from the drawing or from a human decision. Derived values — turning, grinding, boring allowances — are computed by the backend and must not be written as raw facts.

## 8. Generate the card

`craft_generate_process_card` with `mode=official` produces the card. Acceptance: the workbench's `process_card` becomes non-null and the edit endpoint accepts the job.

`craft_edit_process_card` exists for manual row edits after generation. Use it instead of regenerating when only wording changes.

## 9. Export

`craft_export_process_card` through the MCP shell may write the artifact into a directory inside the shell's container, where the caller cannot reach it. Export against the backend instead:

```bash
curl -sS -o process-card.xlsx \
  "http://<backend-host>:5199/api/jobs/<job_id>/process-card/export"
```

Check the returned content type rather than trusting the documentation: some builds return XLSX where the docs say CSV. See [patches/04-timeout-and-export.md](../patches/04-timeout-and-export.md).
