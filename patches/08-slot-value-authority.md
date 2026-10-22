# Patch 8: who owns a slot value

Risk: high if changed carelessly — this is the rule that decides what goes on a shop drawing.

## Three failures, one root cause

**Derived values overwrite confirmed values.** A slot was confirmed as `-0.05/-0.10`. The generated card came back with `-0.05/-0.13`, the value the turning rule computes from the raw diameter. The confirmation was stored, then recomputed during generation.

**Candidate facts bind to the wrong slot.** A Ø64 surface was offered facts of Ø164 and Ø157. The binding matched something — position in a list, an index, a fuzzy name — but not the nominal.

**Tolerance text is accepted without a second look.** `+0.1/0` was read as `+0.01/0`, and the system's own hint said the template differed and the drawing was authoritative — pointing the reader at the wrong number.

The common root: the pipeline treats "a value exists" and "a value was approved" as the same thing, and treats "a fact was found nearby" as "this fact belongs here".

## Rule

A slot has a value and an authority. Authority is ordered:

```
human confirmation  >  drawing fact (verified)  >  rule-derived  >  template default
```

Generation may fill slots that are unconfirmed. It must not replace a confirmed one. If the rule disagrees with a confirmed value, that is a conflict to report, not a correction to apply.

Suggested facts must match on nominal and location. A fact whose nominal differs from the slot's nominal is not a candidate, whatever its confidence.

Ambiguous tolerance text must be preserved verbatim and flagged. Do not normalise `+0.1` and `+0.01` into one form; they are different requirements.

## Implementation sketch

```python
def effective_value(slot):
    if slot.get("confirmed_by"):
        return slot["value"], "human"
    if slot.get("rule_value"):
        return slot["rule_value"], "rule"
    return slot.get("template_value"), "template"
```

Store the source alongside the value and emit it in the card payload and the workbench. When `source == "human"` and `rule_value != value`, include a `conflicts` entry instead of overriding.

For binding:

```python
def candidate_facts(slot, facts):
    return [f for f in facts
            if f["nominal"] == slot["nominal"]
            and overlaps(f.get("location"), slot.get("location"))]
```

An empty result is a correct answer. Returning Ø164 for a Ø64 slot is not.

## Acceptance

Confirm a value, generate, and assert the card contains the confirmed value and a `conflicts` entry if the rule disagrees.

A slot with no matching fact returns no candidates rather than a near miss.

Two tolerances that differ by a decimal place remain two distinct strings end to end.

## Why this is P0

A wrong allowance is not a formatting problem. It changes how much material is left for grinding, and it is discovered at the machine, not in review.
