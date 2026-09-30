# Native simulator performance

This build uses a copied E121 source snapshot. It does not replace the archived
engine or the P300 build. The current target is Apple M4 with Apple Clang 17;
an M4 binary is not a portable runtime for older or non-Apple CPUs.

`agent/heart_simulator_performance.py` prepares the snapshot and runs the
measurements. Set `--root` to a new directory for a new study. The available
builds isolate these changes:

| Build | Core compilation | Source change |
| --- | --- | --- |
| `o3-lto` | O3, apple-m4, ThinLTO | None |
| `pgo-generate` | Above, with execution counters | None |
| `pgo` | Above, using merged counters | None |
| `o3-lto-queue` | O3, apple-m4, ThinLTO | Move callbacks into/out of the queue |
| `pgo-generate-queue` | Instrumented queue variant | Same queue patch |
| `pgo-queue` | Queue variant with its own profile | Same queue patch |

Assertions remain enabled. No fast-math option is used. Core compilation is
configured once, avoiding the old Release `-O3` followed by overriding `-O2`.
All 29 core translation units and the Python binding participate in LTO.

The `prepare` command selects 48 profile roots and 48 timing roots from the
existing P210 workload. Their source families are disjoint. It also selects
eight historical full-run regression families, including a declared Heart
success. These are performance/correctness workloads, not win-rate evaluation.

PGO follows the [Clang instrumentation workflow](https://clang.llvm.org/docs/UsersManual.html#profile-guided-optimization).
Build the instrumented variant, set `LLVM_PROFILE_FILE` to a new directory
containing `%m-%p.profraw`, and run `bench --suite profile`. Merge only those
files with `xcrun llvm-profdata merge`, producing `profile.profdata` or
`queue-profile.profdata` under the study root. Then build the corresponding
`pgo` variant. Do not use timing or acceptance families to generate profiles.

`sweep --rounds 5` rotates five engines through five serial measurement rounds.
Each native battle resolver uses the original 8000 simulations, Boss multiplier
3, and deterministic externally supplied play time. Every measurement checks
the action sequence, actual simulation count, turns, outcome, next game state,
and RNG against the recorded source. A mismatch aborts the comparison; partial
measurements are retained. Imports, prefix replay, and policy-network calls are
excluded from the reported native resolver time. CPU time, wall time, load,
binary hashes, commands, and raw rows are saved.

`agent/heart_performance_runtime.py package --root ... --variant ...` copies the
parent runtime and changes its engine identity and file manifest. `verify`
loads that package through the actual frozen runtime loader, recomputes the
parent neural policy and all combat searches for the eight regression runs,
and requires the complete trajectory and terminal fingerprint to match.
This does not establish original-Java parity or improved Heart win rate.

The callback move patch has separate queue contracts for growth during a
callback, wraparound, copy isolation, and a heap-backed callback surviving
storage reuse. AddressSanitizer/UndefinedBehaviorSanitizer results belong to
the study artifacts. Passing contracts does not establish a speed benefit;
the patch is an optional measured variant until selected in the study result.
