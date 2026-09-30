def choose_teacher(x, parent, gc, actions, descriptors, seed=0):
    arm = ARMS
    seeds = [101, 102, 103, 104]
    simulations = 500
    record_dir = start = stop = None
    sts, A, config = (x.R.sts, x.A, x.config)
    features = set(arm.split('+'))
    boss_multiplier = 12.0 if 'boss12' in features else config['boss_multiplier']
    boss_multiplier = next((float(f[4:]) for f in features if f.startswith('boss') and f[4:].isdigit()), boss_multiplier)
    base_sims = next((int(f[4:]) * 1000 for f in features if f.startswith('sims') and f[4:].isdigit()), config['simulations'])
    adapt = next((float(f[5:]) for f in features if f.startswith('adapt')), None)
    hp_target = next((int(f[2:]) / 100 for f in features if f.startswith('hp') and f[2:].isdigit()), 0.0)
    new_combat_modes = sum((name in features for name in ('reuse', 'refine')))
    if new_combat_modes and (new_combat_modes > 1 or 'fast' in features or adapt is not None):
        raise ValueError('reuse, refine, fast and adaptive combat are separate search policies')
    simulations_used = 0
    overrides = 0
    record = [] if record_dir else None
    prefix = [] if 'traj' in features else None
    explore = next((int(f[7:]) / 100 for f in features if f.startswith('explore') and f[7:].isdigit()), 0.0)
    explore_rng = random.Random(seed * 1000003 + 17)
    explored = 0
    branch = next((int(f[6:]) / 100 for f in features if f.startswith('branch') and f[6:].isdigit()), 0.0)
    branch_rng = random.Random(seed * 7919 + 3)
    elite_thr = next((int(f[5:]) / 100 for f in features if f.startswith('elite') and f[5:].isdigit()), None)
    flame_thr = next((int(f[5:]) / 100 for f in features if f.startswith('flame') and f[5:].isdigit()), None)
    strength_cache = {}
    fixes = 0
    fix3 = dict.fromkeys(FIX3_RULES, 0)
    card_adjusts = 0
    fix3_log = []
    fix4 = dict.fromkeys(FIX4_RULES, 0)
    fix4_log = []
    route_params, route_cache = (None, {})
    guide2_cache = {}
    map_forks = 0
    card_forks = 0
    mapfork_rng = random.Random(seed * 104729 + 11)
    for f in features:
        if f[:2] in ('rv', 'rb') and 'f' in f[2:]:
            e, fl = f[2:].split('f')
            route_params = dict(elite_thr=int(e) / 100, flame_thr=int(fl) / 100, mode='avoid' if f[:2] == 'rv' else 'both')
    guides = 0
    branches = []
    started = time.monotonic()
    bosses, teacher_calls, teacher_changed, steps = ([], 0, 0, 0)
    error = None
    chosen = parent.choose(gc, A.obs_vec(gc), actions, descriptors)
    if 'rest' in features:
        rest = pre_boss_rest(x, gc, actions, descriptors)
        if rest is not None:
            overrides += rest != chosen
            chosen = rest
    if len(actions) > 1 and {'hvsel', 'hvcard', 'hvcard2'} & features:
        indices = teacher_indices(x, gc, actions, descriptors, chosen)
        on_select = gc.screen_state == sts.ScreenState.CARD_SELECT and 'hvsel' in features
        on_card = gc.screen_state == sts.ScreenState.REWARDS and ('hvcard' in features or ('hvcard2' in features and int(gc.act) >= 2))
        if indices and (on_select or on_card):
            best = hv_choice(gc, actions, indices, 0.02)
            if best is not None:
                teacher_calls += 1
                teacher_changed += best != chosen
                chosen = best
    if len(actions) > 1 and {'svsel', 'svcard', 'svcard2'} & features:
        indices = teacher_indices(x, gc, actions, descriptors, chosen)
        on_select = gc.screen_state == sts.ScreenState.CARD_SELECT and 'svsel' in features
        on_card = gc.screen_state == sts.ScreenState.REWARDS and ('svcard' in features or ('svcard2' in features and int(gc.act) >= 2))
        if indices and (on_select or on_card):
            best = sv_choice(gc, actions, indices, 0.01, 'natural' if 'sva1n' in features else 2 if 'sva1x2' in features else 'sva1' in features)
            if best is not None:
                teacher_calls += 1
                teacher_changed += best != chosen
                chosen = best
    late_only = 'late' in features and int(gc.act) < 3
    if 'model' in features and len(actions) > 1 and (not late_only):
        indices = teacher_indices(x, gc, actions, descriptors, chosen)
        if indices:
            scores = model_scores(gc, actions, indices)
            best = max(indices, key=lambda i: scores[i])
            gate = next((int(f[4:]) / 1000 for f in features if f.startswith('gate')), None)
            if gate is not None and chosen in scores and (scores[best] - scores[chosen] <= gate):
                best = chosen
            teacher_calls += 1
            teacher_changed += best != chosen
            chosen = best
    if 'teacher' in features and len(actions) > 1:
        indices = teacher_indices(x, gc, actions, descriptors, chosen)
        if indices:
            detail = {} if record is not None else None
            scores = T.score_candidates(gc, actions, indices, seeds, simulations, detail)
            best = max(indices, key=lambda i: scores[i])
            if record is not None:
                record.append(dict(floor=int(gc.floor_num), act=int(gc.act), screen=int(gc.screen_state), hp=int(gc.cur_hp), max_hp=int(gc.max_hp), parent=chosen, teacher=best, observation=x.R.sparse(A.obs_vec(gc)), descriptors=[x.R.sparse(d) for d in descriptors], actions=[int(a.bits) for a in actions], **detail))
            teacher_calls += 1
            teacher_changed += best != chosen
            chosen = best
    if 'vlate' in features and int(gc.act) >= 3 and (len(actions) > 1):
        pool = None
        if gc.screen_state == sts.ScreenState.REWARDS:
            pool = teacher_indices(x, gc, actions, descriptors, chosen)
        elif gc.screen_state == sts.ScreenState.CARD_SELECT:
            pool = list(range(len(actions))) if gc.selection_count == 1 else None
        elif gc.screen_state == sts.ScreenState.REST_ROOM:
            pool = list(range(len(actions))) if gc.red_key or int(gc.act) >= 4 else None
        elif gc.screen_state in (sts.ScreenState.SHOP_ROOM, sts.ScreenState.BOSS_RELIC_REWARDS):
            pool = list(range(len(actions)))
        if pool and chosen in pool:
            best = vlate_choice(x, gc, actions, pool, chosen)
            teacher_calls += 1
            teacher_changed += best != chosen
            chosen = best
    if 'portal' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN and (gc.event_id_string == 'SecretPortal') and (not gc.red_key):
        leave = [i for i, a in enumerate(actions) if not a.is_potion_action and a.idx1 == 1]
        if leave and leave[0] != chosen:
            overrides += 1
            chosen = leave[0]
    key_act = next((int(f[3:]) for f in features if f.startswith('key') and f[3:].isdigit()), 0)
    if key_act and int(gc.act) < key_act and (not gc.green_key) and (gc.screen_state == sts.ScreenState.MAP_SCREEN):
        better = defer_flame(x, gc, actions, descriptors, chosen)
        if better is not None:
            overrides += 1
            chosen = better
    if (elite_thr is not None or flame_thr is not None) and gc.screen_state == sts.ScreenState.MAP_SCREEN:
        better = route_by_strength(x, gc, actions, descriptors, chosen, elite_thr, flame_thr, strength_cache)
        if better is not None:
            overrides += 1
            chosen = better
    if 'evsafe' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN:

        def dies(i):
            trial = C.F.copy_game(gc)
            actions[i].execute(trial)
            return trial.outcome == sts.GameOutcome.PLAYER_LOSS
        if dies(chosen):
            safe = [i for i, a in enumerate(actions) if not a.is_potion_action and i != chosen and (not dies(i))]
            if safe:
                overrides += 1
                chosen = safe[-1]
    if route_params is not None and gc.screen_state == sts.ScreenState.MAP_SCREEN and (len(actions) > 1):
        import route_rules as RR
        better = RR.route_choice(x, gc, actions, descriptors, chosen, route_cache, route_params)
        simulations_used += route_cache.pop('sims', 0)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'guide2' in features and len(actions) > 1:
        import guide_rules2 as G2
        better = G2.guide_choice2(x, gc, actions, descriptors, chosen, parent, guide2_cache)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'groute2' in features and len(actions) > 1:
        import guide_rules2 as G2
        better = G2.guide_route2(x, gc, actions, descriptors, chosen, parent, guide2_cache)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'guide' in features and len(actions) > 1:
        import guide_rules as G
        better = G.guide_choice(x, gc, actions, descriptors, chosen, parent)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'groute' in features and len(actions) > 1:
        import guide_rules as G
        better = G.guide_route(x, gc, actions, descriptors, chosen)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'baixi' in features and len(actions) > 1:
        import baixi_rules as BX
        better = BX.baixi_choice(x, gc, actions, descriptors, chosen, parent)
        if better is not None and better != chosen:
            overrides += 1
            guides += 1
            chosen = better
    if 'eliteseek' in features and gc.screen_state == sts.ScreenState.MAP_SCREEN and (int(gc.act) <= 3) and (gc.cur_hp >= 0.6 * gc.max_hp) and (int(gc.cur_map_node_y) + 1 < 15):
        y = int(gc.cur_map_node_y) + 1
        maps = [i for i, a in enumerate(actions) if not a.is_potion_action and x.R.kind(descriptors[i]) == A.AK_MAP]
        room = lambda i: gc.map_node_room(int(actions[i].idx1), y).name
        tx, ty, _ = gc.burning_elite

        def reach(cx, cy):
            if ty < 0 or cy > ty:
                return False
            if cy == ty:
                return cx == tx
            return any((reach(k, cy + 1) for k in gc.map_node_children(cx, cy)))
        if chosen in maps and room(chosen) in ('MONSTER', 'EVENT', 'REST'):
            keep_rest = room(chosen) == 'REST' and int(gc.act) == 3 and (not gc.red_key)
            keep_flame = int(gc.act) == 3 and (not gc.green_key) and reach(int(actions[chosen].idx1), y)
            elites = [i for i in maps if room(i) == 'ELITE' and (not keep_flame or reach(int(actions[i].idx1), y))]
            if elites and (not keep_rest):
                overrides += 1
                fixes += 1
                chosen = elites[0]
    if 'fix2' in features and len(actions) > 1:
        better = loss_fixes2(x, gc, actions, descriptors, chosen, parent)
        if better is not None:
            overrides += 1
            fixes += 1
            chosen = better
    if 'fix' in features and len(actions) > 1:
        better = loss_fixes(x, gc, actions, descriptors, chosen, parent)
        if better is not None:
            overrides += 1
            fixes += 1
            chosen = better
    if branch and int(gc.act) <= 2 and (len(actions) > 1) and (branch_rng.random() < branch):
        options = branch_options(x, gc, actions, descriptors, chosen, branch_rng)
        if options:
            outcomes = []
            for i in options:
                trial = C.F.copy_game(gc)
                actions[i].execute(trial)
                r = play(seed, rollout_arm(features), seeds, simulations, start=trial, stop=lambda g: int(g.act) >= 3)
                outcomes.append(dict(index=i, **{k: r[k] for k in ('status', 'act', 'floor', 'hp', 'max_hp', 'error', 'simulations', 'end_features')}))
                simulations_used += r['simulations']
            branches.append(dict(floor=int(gc.floor_num), act=int(gc.act), screen=gc.screen_state.name, hp=int(gc.cur_hp), max_hp=int(gc.max_hp), step=len(prefix or []), observation=x.R.sparse(A.obs_vec(gc)), descriptors=[x.R.sparse(d) for d in descriptors], actions=[int(a.bits) for a in actions], chosen=chosen, outcomes=outcomes))
    if 'relicu' in features and gc.screen_state == sts.ScreenState.BOSS_RELIC_REWARDS:
        table = RELIC_U.get(str(int(gc.act)))
        if table:

            def u(i):
                a = actions[i]
                return table.get('SKIP' if a.idx1 == 3 else sts.RelicId(int(gc.boss_relics[a.idx1])).name, 0.0)
            opts = [i for i, a in enumerate(actions) if not a.is_potion_action]
            best = max(opts, key=u)
            if chosen in opts and u(best) - u(chosen) > 0.03:
                overrides += 1
                chosen = best
    if 'neowfork' in features and gc.screen_state == sts.ScreenState.EVENT_SCREEN and (gc.event_id_string == 'NEOW') and (int(gc.floor_num) == 0):
        outcomes = []
        for i, a in enumerate(actions):
            if a.is_potion_action:
                continue
            option = [int(v) for v in gc.neow_options[a.idx1]] if 0 <= a.idx1 < len(gc.neow_options) else None
            if i == chosen:
                outcomes.append(dict(index=i, option=option, pick=True))
                continue
            trial = C.F.copy_game(gc)
            a.execute(trial)
            r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
            simulations_used += r['simulations']
            outcomes.append(dict(index=i, option=option, pick=False, **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
        branches.append(dict(kind='neow', chosen=chosen, outcomes=outcomes))
    if 'mapfork' in features and gc.screen_state == sts.ScreenState.MAP_SCREEN and (int(gc.act) <= 3) and (map_forks < 3) and (int(gc.cur_map_node_y) + 1 < 15):
        y = int(gc.cur_map_node_y) + 1
        maps = [i for i, a in enumerate(actions) if not a.is_potion_action and x.R.kind(descriptors[i]) == A.AK_MAP]
        rooms = {i: gc.map_node_room(int(actions[i].idx1), y).name for i in maps}
        if chosen in rooms and len(set(rooms.values())) > 1 and ('ELITE' in rooms.values() or mapfork_rng.random() < 0.15):
            map_forks += 1
            tx, ty, _ = gc.burning_elite

            def reach(cx, cy):
                if ty < 0 or cy > ty:
                    return False
                if cy == ty:
                    return cx == tx
                return any((reach(k, cy + 1) for k in gc.map_node_children(cx, cy)))
            reps = {}
            for i in maps:
                if rooms[i] != rooms[chosen]:
                    reps.setdefault(rooms[i], i)
            outcomes = [dict(index=chosen, room=rooms[chosen], pick=True, x=int(actions[chosen].idx1), flame=reach(int(actions[chosen].idx1), y))]
            for room_name, i in sorted(reps.items()):
                trial = C.F.copy_game(gc)
                actions[i].execute(trial)
                r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                simulations_used += r['simulations']
                outcomes.append(dict(index=i, room=room_name, pick=False, x=int(actions[i].idx1), flame=reach(int(actions[i].idx1), y), **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
            branches.append(dict(kind='map', floor=int(gc.floor_num), act=int(gc.act), y=y, hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold), keys=[bool(gc.red_key), bool(gc.green_key), bool(gc.blue_key)], burning=[int(tx), int(ty)], chosen=chosen, outcomes=outcomes, deck=[[int(c.id), int(c.upgrade_count)] for c in gc.deck], relics=[int(r.id) for r in gc.relics], potions=[int(q) for q in gc.potions], boss=int(gc.boss), observation=x.R.sparse(A.obs_vec(gc))))
    if 'cardfork' in features and int(gc.act) <= 3 and (card_forks < 2) and (len(actions) > 1):
        pool = teacher_indices(x, gc, actions, descriptors, chosen)
        if pool and gc.screen_state == sts.ScreenState.REWARDS and (chosen in pool):
            before = T.deck_key(gc)

            def took(i):
                c = C.F.copy_game(gc)
                actions[i].execute(c)
                added, _ = T.deck_delta(before, T.deck_key(c))
                return added[0] if added else 'SKIP'
            names = {i: took(i) for i in pool}
            base = lambda n: n.rstrip('+')
            over = {'UPPERCUT', 'GHOSTLY_ARMOR', 'SHRUG_IT_OFF', 'CLOTHESLINE', 'METALLICIZE'}
            under = {'REAPER', 'EVOLVE', 'BLOODLETTING', 'FEED', 'DEMON_FORM'}
            if base(names[chosen]) in over or any((base(n) in under for i, n in names.items() if i != chosen)):
                card_forks += 1
                outcomes = [dict(index=chosen, card=names[chosen], pick=True)]
                for i in pool:
                    if i == chosen:
                        continue
                    trial = C.F.copy_game(gc)
                    actions[i].execute(trial)
                    r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
                    simulations_used += r['simulations']
                    outcomes.append(dict(index=i, card=names[i], pick=False, **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
                branches.append(dict(kind='card', floor=int(gc.floor_num), act=int(gc.act), hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold), chosen=chosen, outcomes=outcomes, deck=before, relics=[r.id.name for r in gc.relics], boss=int(gc.boss)))
    if 'relicfork' in features and gc.screen_state == sts.ScreenState.BOSS_RELIC_REWARDS:
        outcomes = []
        for i, a in enumerate(actions):
            if a.is_potion_action:
                continue
            rid = None if a.idx1 == 3 else gc.boss_relics[a.idx1]
            if i == chosen and 'relicself' not in features:
                outcomes.append(dict(index=i, relic=getattr(rid, 'name', str(rid)), pick=True))
                continue
            trial = C.F.copy_game(gc)
            a.execute(trial)
            r = play(seed, rollout_arm(features), seeds, simulations, start=trial)
            simulations_used += r['simulations']
            outcomes.append(dict(index=i, relic=getattr(rid, 'name', str(rid)), pick=False, **{k: r[k] for k in ('status', 'win', 'act', 'floor', 'error')}))
        branches.append(dict(floor=int(gc.floor_num), act=int(gc.act), hp=int(gc.cur_hp), max_hp=int(gc.max_hp), gold=int(gc.gold), chosen=chosen, outcomes=outcomes, deck=[[int(c.id), int(c.upgrade_count)] for c in gc.deck], relics=[int(r.id) for r in gc.relics], potions=[int(p) for p in gc.potions], boss=int(gc.boss), observation=x.R.sparse(A.obs_vec(gc))))
    was_explored = False
    if explore and int(gc.act) >= 3 and (len(actions) > 1):
        pool = None
        if gc.screen_state == sts.ScreenState.REWARDS:
            pool = teacher_indices(x, gc, actions, descriptors, chosen)
        elif gc.screen_state == sts.ScreenState.CARD_SELECT:
            pool = list(range(len(actions))) if gc.selection_count == 1 else None
        elif gc.screen_state == sts.ScreenState.REST_ROOM:
            pool = list(range(len(actions))) if gc.red_key or int(gc.act) >= 4 else None
        elif gc.screen_state in (sts.ScreenState.SHOP_ROOM, sts.ScreenState.BOSS_RELIC_REWARDS):
            pool = list(range(len(actions)))
        pool = [i for i in pool or [] if i != chosen]
        if pool and explore_rng.random() < explore:
            chosen = explore_rng.choice(pool)
            was_explored = True
            explored += 1
    if 'fix3' in features and len(actions) > 1:
        better = loss_fixes3(x, gc, actions, descriptors, chosen, parent)
        if better is not None:
            index, rule = better
            overrides += 1
            fixes += 1
            fix3[rule] += 1
            fix3_log.append(dict(rule=rule, act=int(gc.act), floor=int(gc.floor_num), hp=int(gc.cur_hp), screen=gc.screen_state.name, before=int(actions[chosen].bits), after=int(actions[index].bits)))
            chosen = index
    if 'fix4' in features and len(actions) > 1:
        better = loss_fixes4(x, gc, actions, descriptors, chosen, parent)
        if better is not None:
            index, rule = better
            overrides += 1
            fixes += 1
            fix4[rule] += 1
            fix4_log.append(dict(rule=rule, act=int(gc.act), floor=int(gc.floor_num), hp=int(gc.cur_hp), screen=gc.screen_state.name, before=int(actions[chosen].bits), after=int(actions[index].bits)))
            chosen = index
    if 'cardadj' in features and gc.screen_state == sts.ScreenState.REWARDS and (int(gc.act) <= 3) and (len(actions) > 1) and (x.R.kind(descriptors[chosen]) in (x.A.AK_REWARD_CARD, x.A.AK_REWARD_SKIP)):
        before = T.deck_key(gc)

        def took(i):
            c = C.F.copy_game(gc)
            actions[i].execute(c)
            added, _ = T.deck_delta(before, T.deck_key(c))
            return added[0].rstrip('+') if added else None
        names = {i: took(i) for i, a in enumerate(actions) if not a.is_potion_action and x.R.kind(descriptors[i]) in (x.A.AK_REWARD_CARD, x.A.AK_REWARD_SKIP)}
        keep = {'FEED', 'CORRUPTION', 'REAPER', 'OFFERING', 'FEEL_NO_PAIN', 'DARK_EMBRACE'}
        feed = [i for i, n in names.items() if n == 'FEED']
        if feed and names.get(chosen) not in keep:
            chosen = feed[0]
            card_adjusts += 1
        elif names.get(chosen) == 'IMMOLATE':
            rest = [i for i in names if names[i] != 'IMMOLATE']
            if rest:
                j = parent.choose(gc, x.A.obs_vec(gc), [actions[i] for i in rest], [descriptors[i] for i in rest])
                chosen = rest[j]
                card_adjusts += 1
    if prefix is not None:
        prefix.append(dict(kind='outside', action=int(actions[chosen].bits), explored=was_explored))
    return int(chosen)