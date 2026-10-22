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

**B. Upload directly to the backend.** The backend accepts multipart uploads. If you do not know its address, [docs/08-endpoint-discovery.md](08-endpoint-discovery.md) gives the order to try — and `tools/craft_discover.py` verifies a short candidate list instead of scanning ports.

```bash
export CRAFT_BACKEND_URL=http://<backend-host>:5199
python tools/craft_upload.py --file ./drawing.png
# job_id   JOB-20261022-...
# 耗时     1.8s    HTTP 200
```

The script exists because the upload is the one step where a client-side timeout destroys the whole run. `GET /api/jobs` is not a list endpoint — it answers `405`, `Allow: OPTIONS, POST` — so a `job_id` that never arrives cannot be recovered by querying; only by asking a person to look at the workbench. To make that unnecessary, every upload is written to a ledger at `~/.config/craft-process/jobs.jsonl` **before** the bytes are sent:

```json
{"event":"attempt","attempt_id":"…","sha256":"…","file":"…","backend":"…"}
{"event":"result","attempt_id":"…","job_id":"JOB-…"}
```

A timeout leaves an attempt with no result. That is neither success nor failure, and the script says so instead of guessing:

```bash
python tools/craft_upload.py --list            # 成功 / 失败 / 未知，逐条列出
python tools/craft_upload.py --file ./drawing.png --force   # 确认没建出来再重传
```

Exit codes: `0` uploaded, `4` the same file was uploaded within the reuse window (returns that `job_id`; add `--force` to create a second job anyway), `2` state unknown, `3` rejected or unreachable. The default wait is 180 seconds — ten is not enough and is what produces the "did it work?" dead end. Continue the rest of the chain through MCP using the `job_id`.

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

Candidates live in `decision.candidates`, not in `replacement`; `replacement` is null until a template is actually selected. Do not wait for it to populate before matching.

Candidates are ranked by `match_strength`, but that field alone is not enough to choose: a real run produced 25 candidates, all `complete`, of which exactly one had a `template_preview.reference_drawing` equal to the current drawing. Read `template_preview.reference_drawing` before selecting. Matching the current drawing number means the slot values and process text already belong to this part; a different number means you are borrowing another size band.

`craft_select_template` commits one candidate. On real drawings this step can take longer than a client's default timeout. A client-side timeout does not mean the server failed: re-read the workbench and check `revision` and the selected template before retrying.

Acceptance: `blocking_action` advances past template selection. Do not rely on `selected_template_id` being populated — in some builds it stays null on the top level and inside `decision` even after a successful selection, so the stage/blocking state is the reliable signal.

## 7. Fill slots

`craft_update_slots` writes parameter values; `craft_review_slots` records the review decision. Values must come from the drawing or from a human decision. Derived values — turning, grinding, boring allowances — are computed by the backend and must not be written as raw facts.

Two behaviours observed in a real run and worth knowing before you trust a green check:

Candidate fact binding can attach the wrong facts. A slot for a Ø64 surface was offered candidate facts of Ø164 and Ø157, which belong to different diameters. Check that the suggested fact's nominal matches the slot's nominal before accepting it.

Derived slots may be recomputed at generation time, ignoring the value you confirmed. If the card differs from the slot you reviewed, do not assume the review was lost silently: compare the card row with the confirmed slot, and correct the generated card explicitly if needed. See [patches/08-slot-value-authority.md](../patches/08-slot-value-authority.md).

## 8. Generate the card

`craft_generate_process_card` is not always the call that produces the card. In a real run it returned `200` while `process_card` stayed `null`; the official card appeared only after `craft_review_slots`.

So the acceptance check is on state, not on the response: read the workbench and require `process_card.mode == "official"` and a non-null `operations` array. If it is still null after `generate`, call `craft_review_slots` and read again. Exporting before the card exists produces placeholder rows.

`craft_edit_process_card` exists for manual row edits after generation. Use it instead of regenerating when only wording or a derived value needs correcting.

## 9. Export

`craft_export_process_card` through the MCP shell may write the artifact into a directory inside the shell's container, where the caller cannot reach it. Export against the backend instead:

```bash
curl -sS -o process-card.xlsx \
  "http://<backend-host>:5199/api/jobs/<job_id>/process-card/export"
```

Check the returned content type rather than trusting the documentation: some builds return XLSX where the docs say CSV. See [patches/04-timeout-and-export.md](../patches/04-timeout-and-export.md).
