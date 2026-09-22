# E152: existing-family coverage, draft before input audit

Status: design draft. No E152 data assembly, optimizer updates, natural runs or sampling have started. Main task owns implementation and review. Existing Luna remains paused; use it only for actual long waits at20-minute intervals.

E148/E150 show a training-versus-family generalization gap; E151 shows that fixed2000 updates cause part of the degradation and that inner-family stopping restores much of it. E128 previously found no qualifying improvement from1536 to4608 families under a frozen encoder/linear readout. Keep that negative result: the proposed comparison asks about a fully trained nonlinear difference model with internal stopping, and reuses already collected data. It is not evidence that more new sampling is needed.

## Available sources

- Existing E128 joint-label store: `runs/heart-e121-simulator-joint-labels-20260920-01/joint`. Frozen current engine and parent identities remain unchanged. Original `family-groups.json` assigns1536 small fit,3072 additional fit,1024 historical holdout,512 reserved development. Fit groups are disjoint from both external groups.
- Small fit:1184 reached first boss,352 prior failures,4736 boss continuations,4728 conditional-card states.
- Additional fit:2418 reached first boss,654 prior failures,9672 boss continuations,9652 conditional-card states. The654 families have no measured choices in this scope; do not pretend they add branch supervision.
- Accepted first-card alternatives exist for the original1536fit families through E136/E143. Do not reopen E133 or invent equivalent first-card labels for the additional families.
- Inventory proof checked at preparation: label-verification SHA `28c20b59874e1194a59340c893d07d98f7ad0c81a11c731cfae4881633e27327`, status complete, zero faults; raw file hashes and exact filtered tree/terminal bindings still require a new input-admission pass before fitting.

## Comparison to freeze after checking input feasibility

Use a common outer reporting cohort of the original1536 families, with existing E73 threefold roles. The small arm uses original fitting families; the expanded arm adds existing additional-fit families outside the same held fold. No historical holdout or reserved development outcome enters fitting or stopping. Both arms keep the original first-card source; only the boss and conditional-card family pools grow.

Keep stage exposure matched: choose among first-card, boss and conditional-card stages with equal probability; then choose an eligible fitting family and conditional branch uniformly. This is a change from family-first sampling, so fit both arms under the new common sampler; do not reuse E151 as a falsely matched control. Retain prior failures in the1536 reported family denominator. Preserve seed, stage and branch grouping in the inner validation loss as well.

Reuse E150's whole nonlinear public-state model with learned parent offset, paired within-state objective and fixed optimizer recipe. Use E151's predeclared inner-family partition and checkpoint schedule for stopping, then refit outer fitting families. Freeze complete protocol, source identities, sampling weights, support rules, maximum update budget and all tests before launch. No parameter/threshold grid based on outer results.

Retain the first-card and boss-card recorded screens, and compare expanded against small directly. Their scopes are not a deployable complete policy; do not splice incompatible first-card and boss prefixes. A qualifying recorded comparison must precede a separately frozen natural-run candidate and fault/state/RNG checks. The final objective stays one frozen Ironclad A20 Heart policy with at least512 wins in1024 untouched seed families.
