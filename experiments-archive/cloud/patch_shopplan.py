s = open("p300_play_v19.py").read()
def rep(a, b):
    global s
    assert s.count(a) == 1, a
    s = s.replace(a, b)
rep("def play(seed, arm, seeds, simulations, record_dir=None, start=None, stop=None):",
    "def play(seed, arm, seeds, simulations, record_dir=None, start=None, stop=None, shop_ban=None):")
rep("""            _, descriptors, _ = A.build_choices(gc)
            chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
""", """            _, descriptors, _ = A.build_choices(gc)
            if (shop_ban is not None and gc.screen_state == sts.ScreenState.SHOP_ROOM
                    and int(gc.floor_num) == shop_ban[0]):
                # shop-plan fork rollout: this shop visit may not use the banned purchase kinds
                keep = [i for i, a in enumerate(actions)
                        if a.is_potion_action or x.R.kind(descriptors[i]) not in shop_ban[1]]
                actions, descriptors = [actions[i] for i in keep], [descriptors[i] for i in keep]
            chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
""")
rep("""            screen = gc.screen_state.name
            if ('decfork' in features""", """            screen = gc.screen_state.name
            if screen == 'SHOP_ROOM' and 'decfork' in features:
                shop_log.append((int(gc.floor_num), int(x.R.kind(descriptors[chosen]))))
            if ('decfork' in features and screen == 'SHOP_ROOM' and shop_ban is None
                    and int(gc.floor_num) not in shop_seen):
                # shop-plan fork: compare whole shop visits, not first purchases. Each plan bans some purchase
                # kinds for this visit and otherwise shops with the same policy; the main line is the policy plan.
                shop_seen.add(int(gc.floor_num))
                kinds = {int(x.R.kind(descriptors[i])) for i, a in enumerate(actions) if not a.is_potion_action}
                K = {'card': A.AK_SHOP_CARD, 'relic': A.AK_SHOP_RELIC, 'potion': A.AK_SHOP_POTION,
                     'remove': A.AK_SHOP_REMOVE}
                plans = {'leave': set(K.values())}
                plans.update({'no_' + n: {k} for n, k in K.items() if k in kinds})
                if (kinds & set(K.values())) and dec_forks.get('SHOP_PLAN', 0) < 1 and decfork_rng.random() < 0.8:
                    dec_forks['SHOP_PLAN'] = 1
                    floor = int(gc.floor_num)
                    visit = []
                    outcomes = [dict(plan='policy', pick=True, bought=visit)]
                    for name, ban in sorted(plans.items()):
                        r = play(seed, rollout_arm(features), seeds, simulations, start=C.F.copy_game(gc),
                                 shop_ban=(floor, frozenset(int(k) for k in ban)))
                        simulations_used += r['simulations']
                        outcomes.append(dict(plan=name, pick=False,
                                             **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                    shop_plans.append((floor, visit))
                    branches.append(dict(kind='shopplan', screen='SHOP_PLAN', floor=floor, act=int(gc.act),
                                         hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold),
                                         offered=sorted(n for n, k in K.items() if k in kinds),
                                         outcomes=outcomes, deck=T.deck_key(gc),
                                         relics=[r.id.name for r in gc.relics], boss=int(gc.boss)))
            if ('decfork' in features and screen != 'SHOP_ROOM'""")
rep("""                                                                'decfork'))))""",
    """                                                                'decfork'))))""")
rep("    dec_forks = {}\n", "    dec_forks = {}\n    shop_seen, shop_log, shop_plans = set(), [], []\n")
# fill each recorded policy visit with the purchase kinds made on that floor once the game ends
rep("        row['relic_forks'] = branches\n",
    "        for floor, visit in shop_plans:\n            visit.extend(k for f, k in shop_log if f == floor)\n        row['relic_forks'] = branches\n")
open("p300_play_v19.py", "w").write(s)
