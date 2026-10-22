# Patch 13: separate saved, confirmed and gate-passed

Risk: low. Wording and response-shape change; no data migration.

## Problem

Three different facts are reported with one vocabulary:

- the request was **saved**;
- a human **confirmed** the value;
- the gate **passed** and the card may be generated.

A write that stores a value returns a success shape that clients read as confirmation. A validation failure can still return a record whose `status` looks confirmed. An agent then reports "parameters written, ready to generate", and the next call returns `409` or, worse, produces a card with placeholder rows.

This is the same family as [patch 9](09-generate-semantics.md) (a `200` that changes nothing) and [patch 11](11-state-source-consistency.md) (signals from different sources). The fix here is to make the three states explicit in every response that touches slots or the card.

## Change

Every slot- or card-mutating response carries three independent fields:

```json
{
  "saved": true,
  "confirmation": {"state": "human_confirmed", "by": "reviewer", "at": "2026-10-22T09:14:00Z"},
  "gate": {"status": "blocked", "reason": "unresolved_slots", "unresolved": ["slot:outer_diameter:1"]}
}
```

Allowed values:

`saved`: `true` / `false` — the write reached storage. Says nothing about correctness.

`confirmation.state`: `unconfirmed` / `human_confirmed` / `auto_suggested`. Only `human_confirmed` may satisfy the review gate. A value rejected by validation must never come back as `human_confirmed`.

`gate.status`: `ok` / `blocked` / `inconsistent`. `inconsistent` is the explicit signal described in [patch 11](11-state-source-consistency.md) and must never be rendered as success.

Errors should carry an executable next step and, for format failures, an example of the accepted shape:

```json
{"error": "invalid_dimension", "gate": {"status": "blocked"},
 "next_action": "resubmit_with_structured_fields",
 "example": {"nominal": 75.0, "upper_deviation": 0.0, "lower_deviation": -0.2, "unit": "mm"}}
```

Tool descriptions and any human-facing summary must use these three words consistently: saved, confirmed, gate-passed. Do not let "success" stand for any of them.

## Acceptance

- A write with a validation failure returns `saved: true`, `confirmation.state: "unconfirmed"`, `gate.status: "blocked"` — never a confirmed-looking payload.
- A confirmed slot whose gate is still blocked returns `gate.status: "blocked"` with the unresolved list.
- A gate-passed job returns `gate.status: "ok"` and `confirmation.state: "human_confirmed"` for every slot in the card.
- An agent reading only `saved` cannot mistake the state for ready; an integration test asserts the three fields are present on every mutating endpoint.

## Note on scope

This patch does not change which values are accepted; that is [patch 8](08-slot-value-authority.md) and [patch 12](12-structured-dimension-fields.md). It changes what the service *says* about a value it already stored, so that a client's next decision is based on the gate, not on a status code.
