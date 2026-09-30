# Distilled student network (v2)

One ReLU network (`11195 → 384 → 1`, 17 MB) that scores every legal candidate for the out-of-combat
decisions of the P300 teacher (`agent/p300_play_v21.py`) and picks the highest score. Combat is still played
by simulator search. It reads only public state: no seed, RNG, or future rewards.

| File | Contents |
|---|---|
| `models/distill2_frozen.pt` | frozen weights (sha256 `90b93734…fa2b`), schema included |
| `models/freeze.json` | freeze record: hash, schema id, teacher arms, evaluation seeds |
| `models/schema.json` | feature layout (offsets, scales, field order) |
| `models/dev-eval-paired1000.json` | development evaluation, student vs teacher |
| `distill2_*.py` | features, model, training, DAgger pipeline, parity check |
| `INTERFACE.md` | how to load and call it, and how to check a Java bridge bit for bit (Chinese) |

## How it was trained

Behaviour cloning on 3,000 teacher games (`traj-c42` + `traj-c43`), warm-started from the earlier parent
network with shop and card-pick features added, then two DAgger rounds (`round2/student.pt` is the frozen file).

## Development result (not the final acceptance)

Seeds 3900040000–3900040999, same seeds for both, paired:

| | Games completed | Wins | Win rate |
|---|---:|---:|---:|
| Teacher | 987 | 540 | 54.7% |
| Student | 982 | 493 | 50.2% |

Paired difference on 980 common games: **-4.6 points** (95% bootstrap CI -8.2 to -1.0; lost 180, gained 135).
About 1–2% of games in each arm ended in an engine fault and are excluded above. Counting them as losses,
the student wins at least 49.3%. The student agrees with the teacher on 92–94% of map, card-reward and rest
choices but only 72–75% of shop and card-select choices.

This is a development block. **The 1,024-unseen-seed acceptance has not been run**, so 50% is not claimed for
the student. The teacher's 50.1% / 49.5% (other seed blocks) is in the main README; the teacher's 54.7% here is
on this particular seed block.

## Usage

```python
from distill2_model import load_student
student = load_student('student/models/distill2_frozen.pt', encoder=runtime.A)
index = student.choose(gc, actions, descriptors)
```

Needs Python, NumPy, PyTorch, the built `slaythespire` module, and this directory on `sys.path`.
