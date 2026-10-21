# Patch 4: timeouts and export

Risk: low for the timeout; low for export, but it changes where the artifact comes from.

## 4a. Template selection outlives the client timeout

Observed: `select-template` runs longer than the configured request timeout. The client receives a connection error. The workbench afterwards shows the selection committed.

The server did the work; the caller thinks it failed. The dangerous response is a retry, because a second selection can overwrite the first or collide on revision.

Fix in two places.

Raise the shell's backend timeout for long operations. A hard 60 seconds is too short for template matching and selection on real drawings; 180 to 300 seconds is realistic. Prefer a per-operation timeout over one global value: reads should fail fast, selection should wait.

Make the client verify before retrying. After a timeout on any write, read the workbench and compare `revision` and the target field. If the write landed, continue rather than repeat.

A cleaner long-term shape is asynchronous: `select-template` returns `202` with an operation id, and the client polls. That removes the timeout question entirely, at the cost of one more state to model.

## 4b. Export writes where the caller cannot reach

Observed: `export` reports success and no file appears on the caller's side.

Cause: the shell writes the artifact into a download directory inside its own container, for example `/app/downloads`. That path is not shared with the client and usually not with the backend.

Options, in order of preference:

**Return the bytes.** The export tool responds with the artifact as an attachment or base64 payload, subject to a size cap. Simplest for MCP clients, which cannot follow a container path.

**Return a URL the caller can fetch.** Serve the artifact from an endpoint the client can reach, with an expiring token. Requires the shell to expose a download route.

**Bypass the shell.** Export directly against the backend's process-card export endpoint and save the response body. This works today and is what the quick start recommends.

Whatever the route, verify the content type. Some builds return XLSX from an endpoint documented as CSV; a `.csv` suffix on XLSX bytes produces a file that opens as garbage.

## Verification

Selection: after a simulated client timeout, the workbench shows the selection and the revision advanced exactly once.

Export: the bytes received by the caller open in a spreadsheet application, and the content type matches the extension.

## Why not simply retry

Because the operation is not idempotent. A retry cannot distinguish "never ran" from "ran and committed", and the second attempt is at best wasted and at worst destructive. Verify state, then act.
