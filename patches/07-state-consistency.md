# Patch 7: job state consistency

Risk: high if the cause is real; the change itself is structural.

## Symptom observed

Requesting the workbench for job A returned a body whose `job_id` was job B, with feature values from a different drawing. Repeated immediately afterwards, the same request returned job A, and eight consecutive requests stayed on A.

Two different foreign ids appeared across a handful of calls. The pattern is consistent with per-process state behind more than one worker, but one observation is not proof; treat the rest of this page as a checklist for confirming and eliminating it.

## Why it matters more than it looks

Reads that occasionally return another job are confusing. Writes that land on another job are destructive, and the damage is silent: the response looks like success, the revision increments, and a human later finds a feature table that belongs to a different part.

If `feature-review` or `process-card-edit` can be served by a worker holding another job's state, then every write in this service is a coin flip under load.

## Confirm first

Run the same read repeatedly against one `job_id`, at concurrency, and compare the returned `job_id`. A rate above zero is a defect.

Repeat with writes against a scratch job: submit a review, then read the workbench for that job and for the id the response claimed. Either the write is rejected, or it applied somewhere unexpected.

Check whether workers hold state in process memory, whether a shared store exists, and whether sticky sessions are configured.

## Fix

**Key state by job id and persist it in one shared store.** In-memory maps in a multi-worker deployment are the root cause of this class of bug. If the store must be in-process, run one worker.

**Echo the requested id.** Every response carries `job_id`; the shell compares it to the path and returns an error on mismatch instead of forwarding a foreign body.

**Make revisions atomic per job.** Read-modify-write on a shared counter needs a lock or a compare-and-swap. Two concurrent reviews against the same revision must produce one success and one 409, never two successes.

**One writer per job.** Take a per-job lock for the duration of a mutating request, and return 409 with a clear message if it is held.

**Audit every write.** Append `{job_id, revision_before, revision_after, actor, tool, summary}` to an append-only log. When something goes wrong, this is the only way to answer "who changed this".

## Client-side guard, until the server is fixed

Read the workbench before and after every write and compare `job_id` with the intended one. Abort on mismatch.

Do not retry a write whose response could not be attributed to a job. A retry against an unknown state is how a small inconsistency becomes a data loss.

Keep one client per job. The revision scheme detects conflicts but does not merge them, and two agents editing the same card will produce a card neither of them reviewed.

## Acceptance

A concurrency test with N parallel reads for each of several jobs returns the correct id every time.

Two simultaneous reviews against the same revision yield exactly one success and one 409.

A write attempted while another holds the job lock returns 409 with `next_action: "retry after the current operation completes"`.

The audit log can reconstruct the revision history of a job.
