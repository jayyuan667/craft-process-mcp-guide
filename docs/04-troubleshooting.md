# Troubleshooting

Organised by symptom. Each entry starts with what you observe, then what to check, then what to do. Resist the urge to restart things before locating the break; a restart at the wrong layer hides the evidence.

## 1. Tools fail to connect, but the MCP handshake works

Observed: `initialize` returns `200`, `tools/list` returns the expected tools, and every business tool fails with a connection error mentioning a loopback address.

Check: whether the shell and the backend share a host and network namespace. Hit the backend health path from your own machine and from the shell's environment if you can.

Cause: the shell's configured backend base URL is `127.0.0.1` or `localhost`, which resolves inside the shell's namespace. In a container that is the container, not the host.

Action: set the backend base URL to an address routable from the shell's namespace, then recreate the container. `restart` does not re-inject environment variables. See [patches/01-api-base-url.md](../patches/01-api-base-url.md).

## 2. `/health` returns 404 on the MCP port

Observed: the port accepts connections, the root returns `404`, and `/health` returns `404`, yet MCP works.

Check: send `initialize` to `/mcp`.

Cause: not every build exposes a health route on the shell. The root path may also 404 by design.

Action: treat a successful `initialize` as the liveness check. Probe the backend separately for its own health route.

## 3. A tool reports the file does not exist

Observed: `craft_create_job` fails with "file not found", while the file plainly exists on your machine.

Check: where the path resolves. The tool reads from the shell's filesystem, not yours and not the backend's.

Cause: file-by-path across hosts does not transfer anything.

Action: either place the file where the shell can read it, or upload with a multipart POST directly to the backend and continue with the returned job id. The durable fix is the content-based input contract in [patches/03-file-content-input.md](../patches/03-file-content-input.md).

## 4. A write returns 409

Observed: `feature-review`, `slots` or `process-card` returns `409` with a revision mismatch.

Check: the workbench's current `revision` and stage.

Cause: another write advanced the revision after you read it, or you are reusing a revision from an earlier step.

Action: re-read the workbench, apply your intent to the current objects, pass the new revision. Do not loop the same payload: if the revision keeps moving, another client is active and you should stop and reconcile.

## 5. Card generation returns 409 even though candidates exist

Observed: `template-match` returns candidates, `generate` returns `409`.

Check: whether the workbench shows a selected template.

Cause: matching is a preview. Selection is a separate committed state.

Action: call `select-template` with the chosen candidate, then generate.

## 6. Template selection times out

Observed: the client reports a timeout or connection error during `select-template`, but the job is still progressing.

Check: the workbench's `revision`, `decision` and template fields.

Cause: selection can run longer than the client's or shell's request timeout. The server may have committed after the client gave up. A common default of 60 seconds is too short; 180 to 300 seconds is realistic.

Action: read the workbench before retrying. If the selection is present, continue; do not reselect. If not, retry once with a longer timeout. See [patches/04-timeout-and-export.md](../patches/04-timeout-and-export.md).

## 7. Export succeeds but there is no file

Observed: `export` returns success, nothing lands in the caller's directory.

Check: the shell's configured download directory.

Cause: the artifact is written inside the shell's container. The client sees a success response and no artifact.

Action: export directly against the backend's process-card export endpoint and save the response body. Verify the content type: some builds return XLSX even where the documentation says CSV.

## 8. The feature table collapses after a review call

Observed: after submitting a review, statuses become unresolved, values disappear, or counts regress.

Check: what you sent. If the payload contained only feature id and decision, that is the cause.

Cause: the endpoint replaces the whole table. Fields you omit are removed, not preserved.

Action: re-extract or restore from the workbench if you have a copy, then resubmit full objects with `status` set and values as strings. Prevention in [patches/02-feature-review-payload.md](../patches/02-feature-review-payload.md).

## 9. The workbench body names a different job

Observed: you request the workbench for job A and the response's `job_id` is job B, with feature values from another drawing.

Check: re-request and compare `job_id` several times. Confirm the backend is not behind a load balancer with per-process state.

Cause: observed in a deployment whose workers kept workbench state in process memory; requests landing on a different worker returned another job's snapshot.

Action: stop before writing. A review POST against a mismatched workbench can affect the wrong job. Confirm the deployment shares job state across workers, or pin requests to one worker, before continuing. Always compare the response's `job_id` with the requested id after every write.

## 10. The upload times out and there is no job id

Observed: the multipart POST to `/api/jobs` gets no response within the client's wait window. No `job_id` arrives. The workbench cannot be queried because the id is unknown, and the agent stops, asking the user whether a task appeared.

Check: first whether the request even left the machine. Then whether the upload ledger has an attempt for that file — `python tools/craft_upload.py --list`.

Cause: the client gave up before the server answered, which says nothing about whether the job was created. There is no recovery path through the API: `GET /api/jobs` returns `405` with `Allow: OPTIONS, POST`, so jobs cannot be enumerated. A ten-second wait plus no ledger is enough to lose the run.

Action: do not re-upload blindly, but do not deadlock either. Match the file's sha256 against the ledger; if an attempt has no result, the state is genuinely unknown — re-upload with `--force` and disclose that at most one orphan job may exist, which does not affect any existing result. For the next run, upload through `tools/craft_upload.py`, which records the attempt before sending and defaults to a 180-second wait. See [02-quickstart.md](02-quickstart.md) §2 and [05-agent-playbook.md](05-agent-playbook.md) §3.
