"""Predeclared visible-state preparation hypotheses; research harness only."""

POTIONS = ('FAIRY_POTION','GHOST_IN_A_JAR','HEART_OF_IRON','WEAK_POTION',
           'DUPLICATION_POTION','LIQUID_MEMORIES','ANCIENT_POTION','SPEED_POTION',
           'DEXTERITY_POTION','LIQUID_BRONZE','POWER_POTION','STRENGTH_POTION',
           'ESSENCE_OF_STEEL','BLOCK_POTION')


def choose(rule,x,g,actions,descriptors,chosen):
    kinds=[x.R.kind(d) for d in descriptors];A=x.A
    relics={r.id.name for r in g.relics}
    if rule.startswith('rest'):
        threshold=int(rule[4:])/100
        if (int(g.act)==4 and g.screen_state.name=='REST_ROOM' and g.cur_hp<threshold*g.max_hp
                and not relics & {'MARK_OF_THE_BLOOM','COFFEE_DRIPPER'}):
            return next((i for i,a in enumerate(actions) if kinds[i]==A.AK_REST and a.idx1==0),chosen)
    if rule=='potionfirst':
        if (int(g.act)==4 and g.screen_state.name=='SHOP_ROOM' and
                g.potion_count<g.potion_capacity and 'SOZU' not in relics):
            stock=g.get_shop_potions()
            ranking={int(x.R.sts.potion_id_from_name(n)):j for j,n in enumerate(POTIONS)}
            options=[]
            for i,a in enumerate(actions):
                if kinds[i]!=A.AK_SHOP_POTION:continue
                potion,price=stock[a.idx1]
                if potion not in ranking or price<0 or price>g.gold:continue
                if potion==int(x.R.sts.potion_id_from_name('FAIRY_POTION')) and 'MARK_OF_THE_BLOOM' in relics:continue
                options.append((ranking[potion],i))
            if options:return min(options)[1]
    if rule=='lateengine':
        if int(g.act)>=3 and int(g.floor_num)>=45 and g.screen_state.name=='REWARDS' and kinds[chosen] in (A.AK_REWARD_CARD,A.AK_REWARD_SKIP,A.AK_REWARD_SINGING_BOWL):
            cards={c.id.name for c in g.deck}
            priority=['FEEL_NO_PAIN','DARK_EMBRACE','SECOND_WIND','DISARM']
            groups=g.rewards['cards']
            group=int(actions[chosen].idx1) if kinds[chosen]!=A.AK_REWARD_SKIP else 0
            if len(groups)!=1:return chosen
            picks=[]
            for i,a in enumerate(actions):
                if kinds[i]!=A.AK_REWARD_CARD or int(a.idx1)!=group:continue
                c=groups[group][int(a.idx2)]
                if c.id.name in priority and c.id.name not in cards:picks.append((priority.index(c.id.name),-int(c.upgraded),i))
            if picks:return min(picks)[2]
    return chosen
