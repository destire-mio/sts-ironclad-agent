"""Read-only reward instrumentation. No copying/executing actions or RNG reads."""
from collections import Counter


def reward_rows(x, gc, actions, descriptors, chosen, trace, step):
    if gc.screen_state != x.R.sts.ScreenState.REWARDS:
        return []
    kinds = [x.R.kind(d) for d in descriptors]
    A = x.A
    k = kinds[chosen]
    if k not in (A.AK_REWARD_CARD, A.AK_REWARD_SKIP, A.AK_REWARD_SINGING_BOWL):
        return []
    groups = gc.rewards['cards']
    selected_group = int(actions[chosen].idx1)
    # SKIP exits the entire reward screen. Every unclaimed group is a pass.
    group_ids = range(len(groups)) if k == A.AK_REWARD_SKIP else [selected_group]
    deck = list(gc.deck)
    counts = Counter(c.id.name for c in deck)
    out = []
    for group in group_ids:
        offers = [dict(card=c.id.name, upgraded=bool(c.upgraded),
                       upgrade_count=int(c.upgrade_count), copies=counts[c.id.name],
                       type=c.type.name, rarity=c.rarity.name)
                  for c in groups[group]]
        pick = int(actions[chosen].idx2) if k == A.AK_REWARD_CARD else None
        out.append(dict(step=step, act=int(gc.act), floor=int(gc.floor_num),
                        boss_reward=gc.cur_room == x.R.sts.Room.BOSS,
                        room=gc.cur_room.name,
                        group=group, offers=offers, pick=pick,
                        choice=offers[pick]['card'] if pick is not None else 'SKIP',
                        decline='bowl' if k == A.AK_REWARD_SINGING_BOWL else 'skip' if pick is None else None,
                        hp=int(gc.cur_hp), max_hp=int(gc.max_hp),
                        deck=[[c.id.name, int(c.upgrade_count)] for c in deck],
                        relics=[[r.id.name, int(r.data)] for r in gc.relics],
                        trace=trace, chosen=chosen,
                        actions=[dict(index=i, kind=int(ki), group=int(a.idx1), slot=int(a.idx2))
                                 for i, (a, ki) in enumerate(zip(actions, kinds))]))
    return out
