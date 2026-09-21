# E128: data-scale comparison completed without a qualifying candidate

Both frozen fits completed 1,000 updates. Training, live-choice verification and finalization exited 0 with clean worker shutdown. All 1,024 common label-holdout families are accounted for: 786 reached the scoped decision and passed live-choice checks; 238 earlier failures remain in the denominator. These are outcomes from the complete continuation trees, not a new natural-development or unseen-acceptance cohort.

| Policy | Fit families | Holdout wins / 1024 | New / lost wins versus parent | Net | Paired exact p |
| --- | ---: | ---: | ---: | ---: | ---: |
| Frozen parent | — | 87 | — | — | — |
| Small fit | 1536 | 98 | 29 / 18 | +11 | .143865 |
| Expanded fit | 4608 | 93 | 27 / 21 | +6 | .470879 |

Each arm needed at least 20 net wins and p < .05. Neither qualified. Expanded versus small was 13 new wins and 18 lost wins, net −5, p=.473130, also failing the separately registered scale gate. This run provides no evidence that tripling the fit families improves the frozen recipe; it does not establish that more data is always ineffective or that the larger dataset causes a true decline. There was no checkpoint/threshold search, natural candidate evaluation, production adoption or fresh acceptance. The parent remains selected.

The prewritten scope diagnostic reconstructed every chosen leaf after complete learning verification. On the common 1,024 families, 238 fail before the first scoped node and 569 lose under every measured combination. Across the remaining 217 families, at least one measured combination wins. The small model selects 98 winning combinations and misses 119; the expanded model selects 93 and misses 124.

Thus even choosing with knowledge of every terminal result yields 217/1024=21.19% on these trees. The scope is first-Act boss relic followed by the final card offer after the first Act-2 fight, with the rest of the policy fixed. This bound is specific to the measured families, decisions and continuation policy; it is not the project's full-policy or population limit. It also does not show that the 119/124 missed wins are predictable from the public information available at the first choice.

Fit-family accounting, retained separately from the common holdout: small 149 parent wins → 214 model-label wins out of 1,536, measured hindsight 339; expanded 487 → 569 out of 4,608, measured hindsight 1,021. The fit groups have different compositions and denominators, so their raw win-count difference is not a data-scale gain.

The main task verified the original completed-study gate, full learning admission, all paired counts/exact probabilities, diagnostic input hashes and leaf-target reconstruction. The diagnostic used no new games or optimizer updates. Aggregate results and proof hashes are in [e128-data-scale-result.json](e128-data-scale-result.json); per-family diagnostic rows remain local in `runs/heart-e128-scope-diagnostic-20260920-01/report.json`.

Decision: retain the parent and do not repeat this frozen data-scale recipe. E131's prior condition is satisfied, so the main task launched the previously selected 128-fit-family early-card scope diagnostic. It tests whether an Act-1 card followed by a branch-local boss relic creates wins absent from the old scope. The original choice order, complete denominator, resource limits and independent audits apply. E131 is a data-investment diagnostic with no optimizer; learned early-card policy training requires a subsequent evidence-based decision. [E131 launch](e131-launch.json), [frozen design](e128-followup-analysis-plan.md).
