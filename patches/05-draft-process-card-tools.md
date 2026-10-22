# Patch 5: expose the draft process card

Risk: low. Read-mostly additions; one write endpoint that already exists in the UI.

## Problem

The workbench front end has a preview step that MCP cannot reach:

```
GET  /api/jobs/{id}/draft-process-card?revision=N
PUT  /api/jobs/{id}/draft-process-card      { revision, slot_values }
GET  /api/jobs/{id}/draft-process-card/export
```

The page uses it to show the card that *would* be produced, before committing. Users read it, adjust slot values, and only then press "采用并生成工艺". Through MCP an agent can only call `craft_generate_process_card`, which produces the official card directly. The most useful review step in the whole workflow is missing, and the agent has no way to recover the cost of a bad generation except editing after the fact.

## Tools to add

```text
craft_generate_draft_card(job_id, revision?, detail="summary")
    GET /draft-process-card?revision=N
    side effect: none beyond computing and caching the draft

craft_get_draft_card(job_id, detail="summary")
    GET /draft-process-card

craft_update_draft_card(job_id, revision, slot_values, detail="summary")
    PUT /draft-process-card
    side effect: recomputes the draft with new slot values; does not select a template

craft_export_draft_card(job_id, save_dir?)
    GET /draft-process-card/export
    returns bytes or a signed URL, not a container path
```

`slot_values` uses the same shape as `craft_update_slots`: `{ slot_id: { value, action?, selected_fact_id? } }`.

## Contract rules

The draft is not a card. It must never set `process_card.mode=official`, and it must not mark a template as selected. A caller that exports a draft and calls it a process card is making a workflow error the server should not reward.

Generating a draft requires an extracted job; it does not require a selected template in every build. Check the actual backend behaviour and document which is true, because the two imply different gates.

`revision` on the PUT must be honoured. A stale draft update is cheap to recompute, but silently applying it makes the subsequent official generation depend on a state nobody reviewed.

## Why this is worth doing first

It is the cheapest way to raise output quality. An agent that can show a human "here is what the card will look like" before committing gets corrections at the right point. Without it, every correction is a post-hoc edit against a card that already claims to be official.

It also removes an asymmetry that confuses agents: the API they are told to use is strictly less capable than the UI next to it.

## Tests

Draft generation on an extracted job returns operations but leaves `process_card` untouched.

PUT with a stale revision returns 409.

Draft export returns bytes whose header matches the declared type.

Official generation after a draft reflects the slot values set through `craft_update_draft_card`.
