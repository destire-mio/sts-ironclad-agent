import re
src = open('~/sts/principles/agent/p300_play_v21.py').read()
a = "    fix4_log = []\n"
assert src.count(a) == 1
src = src.replace(a, a + "    shop_potions = 0\n")
b = "            if ('cardadj' in features and gc.screen_state == sts.ScreenState.REWARDS and int(gc.act) <= 3\n"
assert src.count(b) == 1
hook = '''            if ('shoppot' in features and gc.screen_state == sts.ScreenState.SHOP_ROOM and int(gc.act) <= 3
                    and not actions[chosen].is_potion_action and x.R.kind(descriptors[chosen]) == A.AK_SHOP_LEAVE
                    and gc.potion_count < gc.potion_capacity
                    and not {r.id.name for r in gc.relics} & {'SOZU'}):
                # shoppot: the policy (almost) never buys potions and enters late bosses empty. Before leaving
                # a shop with an empty slot, buy the best affordable potion (fix3 priority order).
                held = {r.id.name for r in gc.relics}
                stock = gc.get_shop_potions()
                names = {int(sts.potion_id_from_name(n)): n for n in FIX3_POTIONS}
                cands = []
                for i, a in enumerate(actions):
                    if a.is_potion_action or x.R.kind(descriptors[i]) != A.AK_SHOP_POTION:
                        continue
                    potion, price = stock[int(a.idx1)]
                    name = names.get(int(potion))
                    if name is None or price < 0 or price > gc.gold:
                        continue
                    if 'MARK_OF_THE_BLOOM' in held and name in {'BLOOD_POTION', 'REGEN_POTION', 'FAIRY_POTION'}:
                        continue
                    if name == 'BLESSING_OF_THE_FORGE' and not any(c.upgradable for c in gc.deck):
                        continue
                    cands.append((FIX3_POTIONS.index(name), i))
                if cands:
                    shop_potions += 1
                    overrides += 1
                    chosen = min(cands)[1]
'''
src = src.replace(b, hook + b)
c = "    if 'cardadj' in features:\n        row['card_adjusts'] = card_adjusts\n"
assert src.count(c) == 1
src = src.replace(c, c + "    if 'shoppot' in features:\n        row['shop_potions'] = shop_potions\n")
open('~/sts/principles/agent/p300_play_v23.py', 'w').write(src)
print('ok')
