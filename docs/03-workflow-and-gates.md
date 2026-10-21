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

## A review checklist that works

Read the drawing, not just the extraction. For each candidate dimension, compare against the actual annotation. For each detection box, ask whether the geometry inside the box exists at all.

Typical failure modes seen in practice:

Thread callouts misread by OCR, with digits dropped or transposed. A callout of the form `M###x#-#g` becoming something shorter is a red flag; verify against the view.

Overall length taken from a neighbouring dimension line rather than the overall dimension. Cross-check that the value's extension lines actually span the part.

Maximum diameter ambiguous when several diameters are dimensioned on the same end. The largest marked diameter, the sealing-face diameter and the theoretical envelope of a spherical feature are three different numbers; pick the one the template's rule expects and say which you used.

Detection boxes on annotation clusters. A box whose evidence is "dimension lines only" is a false positive; reject it rather than confirming a feature that does not exist.

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
