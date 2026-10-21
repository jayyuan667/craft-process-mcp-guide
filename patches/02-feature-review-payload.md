# Patch 2: merge semantics for feature review

Risk: medium. The current behaviour silently destroys reviewed state; the fix changes a write contract.

## Symptom

A review call succeeds, then the workbench is worse than before: statuses become `unresolved`, `value` disappears, counts regress, and the stage refuses to advance.

## Root cause

The review endpoint replaces the entire feature table with the submitted array. A caller that sends the minimal documented payload:

```json
{ "feature_id": "overall_length:1", "decision": "confirm" }
```

has just told the server that this is the complete table, and that the feature has no role, no value, no confidence and no provenance. The server stores exactly that.

There is no error, because from the server's point of view the request was well-formed. The MCP shell does not compensate: it forwards the caller's array as-is.

A second, independent failure makes this easy to hit: the shell's schema rejects numeric values for `value`, while the extraction returns numbers. A caller that "fixes" the type error by dropping fields rather than stringifying the value lands directly in the first failure.

## Fix, option A: server-side merge

Treat the endpoint as a patch over existing features.

```python
def apply_review(job, items):
    current = {f["feature_id"]: f for f in job.workbench["review"]["features"]}
    for item in items:
        feature = current.get(item["feature_id"])
        if feature is None:
            raise UnknownFeature(item["feature_id"])
        for key in ("status", "decision", "value", "note"):
            if key in item:
                feature[key] = item[key]
        feature["updated_at"] = now()
    job.revision += 1
```

Requirements:

Unknown ids fail loudly rather than being appended.

Omitted fields are preserved.

`value` accepts number or string and is normalised on write.

A full replacement remains available behind an explicit flag or a separate endpoint, so bulk corrections stay possible.

## Fix, option B: keep replacement, make it honest

If the semantics must stay, then make the caller's obligation explicit and enforced:

Require every submitted object to carry `feature_id`, `status`, `role`, and `value`.

Reject arrays that do not cover the current feature set, with an error naming the missing ids.

Accept numeric `value` in the shell schema and coerce.

Document in the tool description: "this replaces the feature table; fetch the workbench first".

Option A is preferable. Replacement semantics are appropriate for bulk import, not for a review gate that a person steps through.

## Client-side workaround until either fix lands

Read the workbench in full, mutate the objects in place, send the entire array back. Set `status` on each item. Convert `value` to a string before sending. Never construct review payloads from ids alone.

## Tests

One test per failure mode, all cheap:

Submit a minimal payload and assert the other fields survive.

Submit a numeric value and assert it is stored.

Submit an unknown feature id and assert a 4xx naming it.

Submit the full table and assert the revision increments once.

Submit two reviews against the same revision and assert the second returns `409`.
