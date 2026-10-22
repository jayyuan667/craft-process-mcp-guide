# Patch 9: generation semantics, counting, export

Risk: low. Behaviour clarification; no data model change.

## `generate` can be a successful no-op

Observed: slots all `confirmed` at revision 6, `craft_generate_process_card` returned `200`, and `process_card` stayed `null`. The official card appeared only after `craft_review_slots`, which took revision 6 to 8.

A `200` that changes nothing is worse than an error, because every client treats `200` as success and moves on. Export then produces rows with placeholder text where values were never confirmed.

Fix one of two ways.

Return `409` with `next_action: "craft_review_slots"` when the card cannot be produced. This is the smaller change and the honest one.

Or make `generate` produce the card by performing the same step `slot-review` performs. This is friendlier but merges two concepts the UI keeps separate.

Either way, the tool description must say which call actually creates the artifact, and the acceptance signal must be state-based: `process_card.mode == "official"` and a non-empty `operations`.

## `rejected` is counted as unresolved

Three false-positive detections marked `status=rejected` left `counts.unresolved` at three. The stage advanced only after `feature_presence` was called. Two different notions of "done" — the count says outstanding work, the state machine says proceed.

Align them. A rejected feature is processed; it should leave the unresolved count and appear in a separate `rejected` count. If the intent is that presence must be explicitly decided, model that as its own blocking state instead of overloading `unresolved`.

Until then, clients must read `blocking_action`, not `counts`, when deciding whether a gate is satisfied.

## Export format and location

The export endpoint returns XLSX (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, magic bytes `50 4B 03 04`) where older documentation says CSV. The MCP tool now sniffs the header and fixes the extension; the docs should say the same thing rather than being corrected at runtime.

The artifact is written on the shell host. A remote caller cannot fetch it. Return the bytes or a signed URL, as described in [patches/04-timeout-and-export.md](04-timeout-and-export.md).

## Tests

`generate` before review returns 409 naming the next tool, or produces a card — not `200` with `null`.

A rejected feature decrements `unresolved` and increments `rejected`.

Export bytes open as a spreadsheet and the declared extension matches the magic bytes.

The MCP export tool, called from another host, yields a file the caller can open.
