# Patch index

Thirteen proposals against the upstream service. They are written in English because they are meant to be reviewed alongside the server code; the narrative documentation is in Chinese.

The **current status** of each patch (implemented, partially mitigated, or still open) is observed behaviour, not a claim about the upstream source. It is maintained in [docs/06-optimization-plan.md](../docs/06-optimization-plan.md), together with the suggested implementation order and acceptance criteria.

| # | Patch | Risk | One line |
| --- | --- | --- | --- |
| 1 | [Configurable backend base URL](01-api-base-url.md) | deployment only | stop resolving the backend at loopback inside the shell |
| 2 | [Merge semantics for feature review](02-feature-review-payload.md) | medium | a partial payload must not replace the whole feature table |
| 3 | [`create_job` accepts file content](03-file-content-input.md) | medium | a path is not a transfer; accept bytes or a URL |
| 4 | [Timeouts and export](04-timeout-and-export.md) | low | per-operation timeouts; deliver the artifact to the caller |
| 5 | [Draft process card tools](05-draft-process-card-tools.md) | low | expose the preview step the UI already has |
| 6 | [`next_action` tool](06-next-action-tool.md) | low | put the next step and its arguments in the protocol |
| 7 | [Job state consistency](07-state-consistency.md) | high to confirm | reads and writes must not land on another job |
| 8 | [Slot value authority](08-slot-value-authority.md) | high | human confirmation outranks derived values |
| 9 | [Generation semantics and counts](09-generate-semantics.md) | low | no successful no-ops; `rejected` is not unresolved |
| 10 | [Backend address discovery](10-backend-address-discovery.md) | low | let `craft_health` disclose the backend it uses |
| 11 | [One validation result](11-state-source-consistency.md) | low to medium | gate signals must agree, or return `state_inconsistent` |
| 12 | [Structured dimension fields](12-structured-dimension-fields.md) | medium | nominal and deviations as numbers; string is display only |
| 13 | [Saved vs confirmed vs gate-passed](13-confirmation-states.md) | low | three states, never one word called "success" |

Patches 1, 2, 3 and 4 have partial client-side workarounds documented in [docs/02](../docs/02-quickstart.md): point the shell at a routable address, send the full feature table back to `feature-review`, upload with multipart, and export directly from the backend. Those workarounds keep a run alive; they do not fix the contract.
