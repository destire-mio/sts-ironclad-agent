# E104/E105 frozen preparation sources

These files preserve the E102-engine renewal of E100/E101's fixed relic/card data-scale study. They are source evidence, not a standalone install: the controllers require the local E103 source gates, E104 label store, frozen runtime, parent weights, and original-game installation. Those private artifacts are not distributed here.

The 15 collector modules are byte-identical to the [E100 archive](../e100-e101-sources/README.md). Driver changes from E100/E101 are experiment names and registered artifact paths. The fixed 1,536/4,608 fits, common 1,024-family holdout, 1,000 updates per arm, learning rate 0.03, L2 0.001, decision scopes and adoption gates are unchanged. No training or new continuation label generation ran in these preparation checks.

`run_collections.py` refuses incomplete source/original gates. `scale_training.py` and `scale_verify.py` require complete new-engine labels. `scale_development.py` and `candidate_original.py` require all downstream gates before candidate selection. The remaining scripts check entry behavior with the observed E102 parent route and software-only zero-head models; those models are not learned candidates.

See [E104 preparation](../e104-label-preparation.json) and [E105 preparation](../e105-training-preparation.json) for checked identities, scope and limits.
