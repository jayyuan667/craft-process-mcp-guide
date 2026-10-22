# Workflow and gates

The service is built around the assumption that extraction is fallible and a human owns the result. The gates are enforced server-side; a client cannot skip them, and a well-behaved client should not try.

## Three gates

**Feature review.** After extraction the workbench enters review. Features split into confirmed facts and items needing review. The server refuses to advance while `blocking_action` is `confirm_features`. Reviewing is not a formality: on real drawings, OCR misreads thread callouts and dimension values, and detection models produce boxes that contain only dimension lines.

**Template selection.** Matching produces candidates. Selecting commits one. Until a template is selected, card generation returns `409`. Candidate lists are recomputed freely; selection is a state change.

**Slot review.** Parameter slots must be filled and reviewed before the card is generated. Slot values carry provenance; the review step is where a human confirms that the provenance is acceptable.

## Provenance rules for values

Three categories, and they must not be mixed:

*Drawing facts.* Values printed on the drawing or measured from it. Safe to write into slots. Preserve the callout as written, including tolerance and thread class.

*Human decisions.* A person confirms or corrects a value. Record it as a decision, not as an extraction.

*Derived values.* Turning, grinding, boring allowances and similar. The backend computes these from rules. Writing them as raw facts double-counts them and corrupts downstream calculations.

When a value is uncertain, the correct action is to leave it for review, not to guess. A fabricated dimension is worse than a missing one because it passes every downstream check.

## Precedence when the server disagrees with the drawing

A human-confirmed slot value is supposed to outrank a rule-derived value. Do not assume it does. In a real run, a slot confirmed as `-0.05/-0.10` came back in the generated card as `-0.05/-0.13`, the value the turning rule computes from the raw diameter. The confirmation was recorded, then overridden during generation.

The practical rule: after generating, compare every derived slot in the card against the value you confirmed. Where they differ, decide which is right by looking at the drawing and the template, then correct the card with `craft_edit_process_card`. Do not "fix" it by re-running the review; if the rule recomputes on generation, it will be overwritten again.

The same caution applies to suggested facts. Candidate facts can be bound to the wrong slot: a Ø64 surface was offered Ø164 and Ø157 as candidates. Match the nominal before accepting a suggestion.

Tolerance text is the weakest link. A real drawing's `+0.1/0` was read as `+0.01/0`, and the service's own hint — "the template differs, take the drawing as authoritative" — pointed at the wrong number. Enlarge the region and read the original text before accepting any tolerance.

## Counting semantics

`rejected` is not the same as processed. In one run, three false-positive detections were marked `status=rejected` and `counts.unresolved` stayed at three, blocking nothing but reporting unresolved work forever. The stage only advanced after `feature_presence` flipped the structural features. Read `blocking_action`, not `counts`, when deciding whether the gate is satisfied.

## A review checklist that works

Read the drawing, not just the extraction. For each candidate dimension, compare against the actual annotation. For each detection box, ask whether the geometry inside the box exists at all.

Typical failure modes seen in practice:

Thread callouts misread by OCR, with digits dropped or transposed. A callout of the form `M###x#-#g` becoming something shorter is a red flag; verify against the view.

Overall length taken from a neighbouring dimension line rather than the overall dimension. Cross-check that the value's extension lines actually span the part.

Maximum diameter ambiguous when several diameters are dimensioned on the same end. The largest marked diameter, the sealing-face diameter and the theoretical envelope of a spherical feature are three different numbers; pick the one the template's rule expects and say which you used.

Detection boxes on annotation clusters. A box whose evidence is "dimension lines only" is a false positive; reject the box, not necessarily the feature. A real case: the keyway box landed on a dimension cluster, while the drawing's technical requirements explicitly said "keyway and 5 mm around it not nitrided" and the section view showed the keyway. The box was wrong and the feature existed. Judge box accuracy and feature presence separately.

Candidate templates with identical match strength. Twenty-five candidates can all be `complete`. Choose by `template_preview.reference_drawing`, not by score alone. The one whose reference drawing equals the current drawing is the one whose slot values already belong to this part.

## What the card does and does not contain

`reference_drawing` in the generated card is the **template's source drawing number**, not the drawing you uploaded. Reading it as the current part's number is a common mistake.

Technical requirements are bound selectively. Only the requirement items referenced by the template's body text are pulled into the card. A drawing with five requirements may produce a card carrying two. If a requirement matters and is missing, check whether the template references it before assuming a bug.

## Concurrency

Writes carry `revision`. A mismatch returns `409`. The correct response is to re-read the workbench, reconcile your intent with the current state, and then write again. Blind retry either fails repeatedly or, on deployments that auto-fill the revision, silently overwrites someone else's decision.

Do not run two clients against the same job. The revision scheme detects conflicts but does not merge them.

## Red lines

Do not write values that are not on the drawing or confirmed by a person.

Do not treat candidates as selections.

Do not treat derived values as facts.

Do not skip review to save a round trip. The gate exists because the extraction is wrong often enough to matter, and the cost of a wrong process card is paid on the shop floor.
