# Heart terminal validation fixtures

These are recorded natural-start Ironclad A20 games from the training-only
`heart-total-data-20260915-01` collection. They are regression inputs, not unseen
evaluation successes. Neither game uses an injected deck or a fabricated terminal.

- `heart-portal-101890269.json.gz`: Secret Portal on floor 47, Act 3 bosses on
  floors 48/49, Shield and Spear on 53, Heart on 54, victory room on 55, 56 HP,
  all three keys. The original fixed-floor validator rejected this game.
- `heart-ordinary-1045458017.json.gz`: ordinary route ending on floor 57.

Collection inputs: `RoleTeacher(1)`, natural seed constructor at ascension 20,
8,000 MCTS simulations per base search, boss multiplier 3, fixed elapsed-time
input of 45 seconds per visited floor, no Prismatic Shard. The regression tests
replay recorded combat actions and verify every state/RNG fingerprint; policy
verification recomputes the teacher's outside choices. The acceptance unit test
substitutes the recorded trace for its expensive fresh MCTS repeat; it does not
claim a new unseen-seed or original-Java evaluation.

Frozen collection SHA-256 values:

- engine: `9bcc137222d051ae58d437cf0f5551db807bff2815f78ca604eb189fa0fddfe2`
- observation encoder `armG_train.py`: `582ebb743571fb3bce500d59d84bd79a26e7eb957eba01222f8d408fd892e8f7`
- teacher: `3a58c4b355eea680422cecd66aef9c092940809a2d153c5d98633461022757ce`

Set `STS_LIGHTSPEED_BUILD` to a compatible engine build when running these tests.
Engine, observation, or fingerprint-format changes may require recollection and
an explicit review of the fixture differences.
