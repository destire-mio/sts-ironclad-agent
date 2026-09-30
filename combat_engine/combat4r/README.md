# combat4r — combat engine used by the P300 teacher

Snapshot of the combat-search engine behind the adopted teacher (`agent/p300_play_v21.py`):
optimized `sts_lightspeed` core, subtree-reuse search, and the post-battle HP scoring revision
(`victory-hp-20260929`, see `report.md`).

- `engine-source/` — engine sources (headers, sources, Python bindings).
- `agent/` — the `fightsim.cpp`, search-reuse header and driver files as built with this engine.
  They differ from the copies in `../../agent/`; build the engine and `fightsim` from the same snapshot.
- `build.py`, `package.py`, `tools/` — the build/packaging/audit scripts used for delivery. They
  chain to earlier delivery directories (`combat4q`) that are not in this repository, so they document
  the procedure rather than run standalone.

Not included: validation evidence, input snapshots and prebuilt binaries (about 370 MB).
