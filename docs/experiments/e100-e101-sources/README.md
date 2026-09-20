# E100 / E101 frozen driver sources

These are exact copies of the registered local experiment drivers, for code review and reproduction. They contain no models, labels, game JARs, native binaries or raw traces. Public report hashes identify the corresponding frozen versions.

Run the collector from its registered experiment directory with `python run_collections.py check-gates --root <collector-directory>` and `python run_collections.py pipeline --root <collector-directory>`. The `frozen/` directory and local protocol/registration/runtime files are required. Source and original-game gates must pass before collection.

The training files belong in the registered `heart-e98-scale-training-20260920-01` directory alongside its protocol and registrations. They read the sibling `heart-e98-scale-source-refresh-20260920-01` and `heart-e98-scale-joint-labels-20260920-01` directories. Run `python scale_training.py train`, then `python scale_verify.py verify`. These commands require complete, hashed local source and continuation evidence. They do not select final acceptance seeds or publish a model.

The source archive is not a claim of portable installation: original-game adapters and macOS native builds remain local prerequisites. `collector/frozen/` preserves historical helpers; the registered wrapper selects only preparation, collection and audit functions, not their legacy training entry points.
