# Patch 11: one validation result behind every gate signal

Risk: low to medium. Adds one error path; changes no data model.

## Symptom

The workbench looks ready to generate while detailed validation says it is not. Observed in a real run: the summary reported no unresolved slots, `blocking_action` had moved past slot review, and `replacement.validation.status` was `partial` with unresolved slots still listed.

A client that reads only the summary generates and exports a card built on unconfirmed values. A client that reads only the detailed validation stalls, because the state machine has already moved on.

## Root cause

`counts`, `blocking_action`, and `validation` are computed from different sources. Each is individually plausible; together they are contradictory. Nothing in the protocol says which one is authoritative, so every client invents a precedence order, and different clients choose differently.

There is also a counting defect that feeds the same symptom: `status=rejected` features stay in `counts.unresolved` (see [patch 9](09-generate-semantics.md)), so the summary can be pessimistic while the gate has advanced, or optimistic while validation has not finished.

## Change

Derive all gate-visible signals from a single validation result, computed once per revision:

```json
{
  "validation": {
    "status": "partial",
    "unresolved_slots": ["slot:outer_diameter:1"],
    "blocking_action": "review_slots",
    "checked_revision": 7
  }
}
```

Requirements:

`counts`, `blocking_action`, `validation.status` and `unresolved_slots` must be projections of that one object, not independent queries. If they disagree, the response is a bug, not a judgement call for the client.

When the projections would disagree, return an explicit error instead of a workable-looking payload:

```json
{
  "error": "state_inconsistent",
  "checked_revision": 7,
  "signals": {"validation_status": "partial", "blocking_action": "generate", "unresolved_slots": 1},
  "next_action": "reload_workbench"
}
```

`blocking_action` must never advance while `validation.status` is `partial` or `unresolved`. Generating under that combination returns `409`, not `200`.

## Acceptance

- A job with one unresolved slot returns `validation.status != "ok"` and `blocking_action == "review_slots"`, consistently across `get_workbench`, `craft_health` and any summary tool.
- `generate` against that job returns `409` with `next_action: "review_slots"`.
- Forging a response where the three signals disagree is caught by an integration test.
- `checked_revision` is present and equals the revision the signals were computed from.

## Client behaviour until this lands

Read all four fields (`validation.status`, `unresolved_slots`, `blocking_action`, `process_card`) before generating. If they disagree, re-read once; if they still disagree, stop and report rather than picking a winner. The rule is written for agents in [docs/05](../docs/05-agent-playbook.md).
