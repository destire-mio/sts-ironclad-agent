# E101D natural-development and original-gate drivers

These are frozen local experiment sources, registered before E101 candidate outcomes. They implement the previously specified two-arm development screen; they do not change the learner or supply a trained model.

The local registered runtime places these files alongside `scale_training.py` from the [E100/E101 training source archive](../e100-e101-sources/training/scale_training.py). Execution also requires the local source/label/training proofs, immutable checkpoints, simulator runtime and original-game adapters. Those private artifacts are not distributed here. This directory is a review/source archive, not a standalone installable runner.

After all E99/E100/E101 learning gates complete:

1. `python scale_development.py natural --arm small` and the corresponding `expanded` command run only the arms that pass the fixed heldout gate. Each accepted arm uses all the same512 development families and a new output directory; a failed/partial attempt cannot be resumed or replaced.
2. `python scale_development.py prepare-original --arm ARM` admits only a natural-screen passing arm. Run `python candidate_original.py --root REGISTERED_ORIGINAL_DIRECTORY` once, checking every winning route with one isolated original instance at a time. Keep mutable observer files outside that directory.
3. `python scale_development.py finalize` requires complete original gates for every natural-passing arm, then selects by wins, lost parent wins, and small on a tie. It does not adopt the policy or generate unseen acceptance seeds.

`check-development-entry.py` records software-only negative controls and a known repaired-engine parent-route replay with an existing zero-head fixture. It performs no new MCTS, optimization or original JVM runs. The retained first checker attempt expected the wrong exception type for a correctly rejected terminal-HP mutation; the second checker changes only that expected exception and its separate output directory.
