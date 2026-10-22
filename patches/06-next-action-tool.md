# Patch 6: a `next_action` tool

Risk: low. Pure read, no side effects. Highest leverage per line of code in this whole plan.

## Problem

The workbench already knows what is blocking: `blocking_action`, `current_stage`, `counts`, and on failures `unresolved_slots` plus `next_action`. None of it is expressed in a form an agent can act on directly. So every client re-derives the state machine from prose, and every client gets some part of it wrong — generating before selecting, reviewing values instead of presence, exporting from the wrong endpoint.

The fix is not more documentation. It is to put the next step in the protocol.

## Tool

```text
craft_next_action(job_id, detail="summary")
```

Read-only. Never writes, never advances state, never fills `revision` on the caller's behalf.

Response:

```json
{
  "job_id": "...",
  "revision": 10,
  "stage": "replace",
  "blocking_action": "confirm_slots",
  "next": {
    "tool": "craft_review_slots",
    "why": "3 slots unresolved; template text is retained until they are confirmed",
    "args": {
      "job_id": "...",
      "revision": 10,
      "values": { "T04-30-1": { "value": "", "action": "confirm" } }
    }
  },
  "alternatives": [
    { "tool": "craft_update_slots", "why": "only if a value needs correcting before review" }
  ],
  "do_not": [
    "craft_generate_process_card: blocked until slots are reviewed"
  ]
}
```

`args` is a skeleton, not a decision: `value` is left empty where a human or the drawing must supply it. The tool must not invent values, template ids or slot ids.

## Mapping

Derive `blocking_action` from the workbench, then map one-to-one:

| `blocking_action` | `next.tool` |
| --- | --- |
| `confirm_features` | `craft_feature_presence` |
| `review_features` | `craft_feature_review` |
| `select_template` | `craft_template_match` then `craft_select_template` |
| `confirm_slots` | `craft_review_slots` |
| `generate_card` | `craft_generate_process_card` |
| `export_card` | `craft_export_process_card` |
| terminal / none | omit `next`, say so explicitly |

Two entries deserve care. If `blocking_action` says review features but the values are already correct, the honest answer is presence, not value review — the two are different writes on this backend. If a template is only matched and not selected, `next.tool` must be selection, and `do_not` must list generation.

## Rules

Echo `job_id` and compare it with the requested id; a mismatch is an error, not a response.

Report `revision` without auto-filling it into the caller's later writes. The whole point of the revision check is that the caller noticed it.

Include `unresolved_slots` verbatim when present. Truncating it is how agents end up "confirming" a subset.

Keep the text short. `why` is one sentence; anything longer becomes documentation again.

## Acceptance

An agent given only `tools/list` and this tool, with no guide, completes upload → export on a fresh drawing.

The response for a blocked job names exactly one primary tool and at least one `do_not`.

No call to `craft_next_action` changes the workbench revision.
