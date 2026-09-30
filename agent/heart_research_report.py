"""Build descriptive and paired evidence from immutable Heart research rows."""
import collections
import gzip
import json
import math
from pathlib import Path
import statistics

OUT=Path(__file__).resolve().parent.parent/'runs/heart-research-20260929'
mean=lambda xs:statistics.mean(xs) if xs else 0


def binomial_interval(k,n,alpha=.025):
    """Clopper-Pearson; alpha=.025 per component permits a Bonferroni 95% delta interval."""
    def quantile_cdf(count,target):
        lo,hi=0.,1.
        for _ in range(60):
            p=(lo+hi)/2
            cdf=sum(math.comb(n,i)*p**i*(1-p)**(n-i) for i in range(count+1))
            if cdf>target:lo=p
            else:hi=p
        return (lo+hi)/2
    return (0. if k==0 else quantile_cdf(k-1,1-alpha/2),
            1. if k==n else quantile_cdf(k,alpha/2))


def rows(path):
    return [json.loads(s) for s in Path(path).read_text().splitlines() if s.strip()]


def table(header,data):
    return '\n'.join(['| '+' | '.join(header)+' |','|'+'|'.join(['---']*len(header))+'|']+
                     ['| '+' | '.join(str(x) for x in r)+' |' for r in data])


def phase_metrics(trace):
    """Keep end-turn selections with the queued end-turn/enemy sequence."""
    ending = False
    own_loss = end_loss = 0
    for item in trace:
        if item['type'] == 'END_TURN':
            ending = True
        terminal_ending = ending
        loss = max(0, item['before']['hp'] - item['after']['hp'])
        if ending:
            end_loss += loss
        else:
            own_loss += loss
        if item['after']['turn'] != item['before']['turn']:
            ending = False
    return dict(player_sequence_loss=own_loss, end_sequence_loss=end_loss,
                terminal_end_sequence=terminal_ending)


def profile_report():
    profiles=rows(OUT/'profiles.jsonl');facts={};text=['# 心脏画像与轨迹审计','',
      '数据范围：c38 的 1000 局；c37 取不重叠的后 1000 个种子作描述性复核。只下载进入第四幕的轨迹及 c38 第三幕 45 层后的死亡轨迹。',
      '画像检查覆盖记录动作合法性、每战 outcome、整局 status/act/floor/HP/max HP。历史文件没有逐步私有状态指纹，不能宣称完成原版游戏全状态一致性验证。',
      '关联用于提出分叉假设，不能把拥有某张牌的胜率差解释成抓取该牌的收益。入场 HP 同时给出战前 GameContext 与开战遗物触发后的数值。','']
    for cohort in ('traj-c38','traj-c37'):
        group=[r for r in profiles if r['cohort']==cohort]
        rs=[r for r in group if r.get('heart')]
        cache={r['seed']:json.load(gzip.open(r['trace'],'rt')) for r in rs}
        phases={r['seed']:phase_metrics(cache[r['seed']]) for r in rs}
        (OUT/f'{cohort}-phase-accounting.json').write_text(json.dumps(phases,indent=2))
        wins=[r for r in rs if r['win']];deaths=[r for r in rs if not r['win']]
        summary=[]
        for label,part in [('胜',wins),('负',deaths)]:
            summary.append([label,len(part),round(mean([r['heart']['hp'] for r in part]),2),
                round(mean([cache[r['seed']][0]['before']['hp'] for r in part]),2),
                round(mean([r['heart']['max_hp'] for r in part]),2),round(mean([r['heart']['deck'] for r in part]),2),
                round(mean([sum(c['type']=='POWER' for c in r['heart']['cards']) for r in part]),2),
                round(mean([r['heart']['potions'] for r in part]),2)])
        text+=['## '+cohort,'',table(['终局','局数','战前HP','首动作HP','最大HP','牌数','能力牌数','药水数'],summary),'']
        bins=[]
        for lo,hi in [(0,.5),(.5,.8),(.8,1.01)]:
            part=[r for r in rs if lo<=cache[r['seed']][0]['before']['hp']/r['heart']['max_hp']<hi]
            bins.append([f'{lo:.0%}–{min(hi,1):.0%}',len(part),sum(r['win'] for r in part),f'{mean([r["win"] for r in part]):.1%}'])
        text+=[table(['开战HP比例','局数','胜局','胜率'],bins),'']
        factors=[]
        for field in ('card','relic','potion'):
            def values(r):
                return set(c['id'] for c in r['heart']['cards']) if field=='card' else set(r['heart']['relic_names'] if field=='relic' else r['heart']['potion_names'])
            for name in sorted(set().union(*(values(r) for r in rs))):
                yes=[r for r in rs if name in values(r)];no=[r for r in rs if name not in values(r)]
                if not yes or not no:continue
                a=mean([r['win'] for r in yes]);b=mean([r['win'] for r in no])
                factors.append(dict(type=field,name=name,n=len(yes),win=a,without=b,delta=a-b))
        (OUT/f'{cohort}-factors.json').write_text(json.dumps(factors,indent=2))
        qualified=[f for f in factors if f['n']>=20 and len(rs)-f['n']>=20]
        selected=sorted(qualified,key=lambda f:f['delta'],reverse=True)[:12]+sorted(qualified,key=lambda f:f['delta'])[:8]
        text+=['描述性区分度（至少 20 个携带样本，未控制构筑与路线混杂）：','',table(['类别','因素','携带数','携带胜率','未携带胜率','差/百分点'],
          [[f['type'],f['name'],f['n'],f'{f["win"]:.1%}',f'{f["without"]:.1%}',f'{100*f["delta"]:+.1f}'] for f in selected]),'']
        requested=['CORRUPTION','BARRICADE','DEMON_FORM','REAPER','FEEL_NO_PAIN','DARK_EMBRACE','SECOND_WIND','DISARM','EVOLVE','POWER_THROUGH','IMPERVIOUS','SHRUG_IT_OFF','BODY_SLAM','LIMIT_BREAK','SPOT_WEAKNESS','POMMEL_STRIKE','FIEND_FIRE']
        text+=['指定构筑因素：','',table(['牌','携带数','携带胜率','未携带胜率'],[[n,f['n'],f'{f["win"]:.1%}',f'{f["without"]:.1%}'] for n in requested for f in factors if f['type']=='card' and f['name']==n]),'']
        turns=collections.Counter(r['last']['before']['turn'] for r in deaths)
        actions=collections.Counter((r['last']['type'],r['last']['before']['intent']) for r in deaths)
        text+=['死亡回合：'+', '.join(f'T{k}: {v}' for k,v in sorted(turns.items()))+'。','',
          table(['终结动作','当时意图','局数'],[[k[0],k[1],v] for k,v in actions.most_common()]),'',
          '终结动作不等于完整死因。CARD/选牌死亡可能含自伤、遗物与触发链；END_TURN 包含燃烧、状态与敌人行动。',
          f'败局中 {sum(r["cap_actions"]>0 for r in deaths)} 局在 Invincible 余量为 0 时仍出攻击牌；这些牌可能带抽牌/格挡/力量/遗物触发，因此计数不等于可删除动作。',
          f'按结束回合序列追踪（选牌暂停后继续执行仍归入该序列）：{sum(phases[r["seed"]]["terminal_end_sequence"] for r in deaths)} 局死于结束回合序列，{sum(not phases[r["seed"]]["terminal_end_sequence"] for r in deaths)} 局死于玩家出牌序列。',
          f'败局玩家出牌序列净掉血合计均值 {mean([phases[r["seed"]]["player_sequence_loss"] for r in deaths]):.2f}，结束回合序列 {mean([phases[r["seed"]]["end_sequence_loss"] for r in deaths]):.2f}；回血单独发生时，累计掉血可超过入场 HP。原 profiles.jsonl 两个 loss 字段按动作类型分组，阶段归属以 phase-accounting.json 为准。','']
        status_turns=[];setup=[]
        for r in rs:
            ts=cache[r['seed']];starts={}
            for t in ts:starts.setdefault(t['before']['turn'],t['before'])
            status_turns.append(dict(seed=r['seed'],win=r['win'],turns_with_two_status=sum(sum(c in ('STATUS','CURSE') for c in s['hand_types'])>=2 for s in starts.values())))
            for power in ('CORRUPTION','BARRICADE','DEMON_FORM','FEEL_NO_PAIN','DARK_EMBRACE','EVOLVE'):
                visible=[t['before']['turn'] for t in ts if any(c.rstrip('+')==power for c in t['before']['hand'])]
                played=[t['before']['turn'] for t in ts if t.get('card')==power]
                if visible:setup.append(dict(seed=r['seed'],win=r['win'],power=power,first_visible=min(visible),first_play=min(played) if played else None))
        (OUT/f'{cohort}-setup.json').write_text(json.dumps(setup,indent=2))
        (OUT/f'{cohort}-status-hands.json').write_text(json.dumps(status_turns,indent=2))
        key_summary={}
        for idx,name in enumerate(('red','green','blue')):
            key_summary[name]=dict(collections.Counter(e['act'] for r in rs for e in r['keys'] if not e['before'][idx] and e['after'][idx]))
        text+=['钥匙取得幕次：`'+json.dumps(key_summary)+'`。本样本按进入心脏筛选，缺钥匙的失败不能用此表估计。','']
        facts[cohort]=dict(act4=len(group),heart=len(rs),wins=len(wins),deaths=len(deaths),turns=dict(turns),summary=summary)
    if (OUT/'profile-addendum.md').exists():text+=['',(OUT/'profile-addendum.md').read_text()]
    (OUT/'profile-facts.json').write_text(json.dumps(facts,indent=2));(OUT/'profile.md').write_text('\n'.join(text))


def cases_report():
    profiles=rows(OUT/'profiles.jsonl');lines=['# 典型心脏败局逐回合证据','',
        '回合从 1 起算；HP 为该回合首动作前到该回合最后记录动作后。最后动作若为结束回合，其后状态含敌人行动及下回合启动。','']
    for seed in (3900012021,3900012321,3900012175,3900012947,3900012025):
        r=next(r for r in profiles if r['seed']==seed and r['cohort']=='traj-c38');ts=json.load(gzip.open(r['trace'],'rt'))
        lines += [f'## Seed {seed}','',f'入场 {r["heart"]["hp"]}/{r["heart"]["max_hp"]} HP；{r["heart"]["deck"]} 张牌。',
                  '牌组：'+', '.join(c['id']+('+' if c['up'] else '') for c in r['heart']['cards'])+'。',
                  '遗物：'+', '.join(r['heart']['relic_names'])+'。','药水：'+', '.join(r['heart']['potion_names'])+'。','']
        data=[]
        for turn in sorted(set(t['before']['turn'] for t in ts)):
            a=[t for t in ts if t['before']['turn']==turn];before=a[0]['before'];after=a[-1]['after']
            cards=collections.Counter(t.get('card',t['type']) for t in a)
            data.append([turn,f'{before["hp"]}→{after["hp"]}',f'{before["monster_hp"]}→{after["monster_hp"]}',
                         before['intent'].replace('CORRUPT_HEART_',''),before['monster_strength'],
                         sum(t.get('card_type')=='ATTACK' and t['before']['invincible']==0 for t in a),
                         ', '.join(f'{k}×{v}' for k,v in cards.items())])
        lines += [table(['回合','玩家HP','心脏HP','意图','心脏力量','封顶后攻击','出牌/动作'],data),'',f'完整顺序、手牌、格挡、能量、能力状态与药水：`{r["trace"]}`。','']
        snapshots=[]
        for turn in sorted(set(t['before']['turn'] for t in ts)):
            part=[t for t in ts if t['before']['turn']==turn]
            ending=next((t for t in part if t['type']=='END_TURN'),None)
            state=ending['before'] if ending else part[-1]['after']
            snapshots.append([turn,', '.join(part[0]['before']['hand']),
                f'{state["hp"]} HP / {state["block"]} 格挡',
                '结束回合前' if ending else '终结动作后'])
        lines += [table(['回合','回合首个决策的手牌','防御快照','快照位置'],snapshots),'']
    lines+=['## 样本解释','',
      '- 3900012021：T2 的多段攻击杀死玩家；保留该回合起手和结束回合前手牌，区分状态牌占位与主动消耗完手牌。',
      '- 3900012321：战前 13 HP，T2 大攻击后剩 1 HP；主要能力 T3 才开始部署。T8 死在连打攻击的过程中。更多预算是否救回须看同平台 paired 行，不能把本机搜索胜利当作对云端历史败局的因果收益。',
      '- 3900012175：T2 多段攻击后剩 18 HP；T4–T6 每回合打满 200 上限，T6 循环产生大量状态牌与触发；封顶后的攻击不全部无效，消耗/抽牌可补格挡。',
      '- 3900012947：T3 为部署能力与抽牌付出血量，T4 打出 COMBUST。T6 剩 1 HP，T7 心脏为 BUFF 意图，仍在结束回合时死亡；轨迹与源码支持自身 Combust 的 1 HP 成本，不能标为心脏攻击击杀。',
      '- 3900012025：用于核对输出上限与防御缺口的另一份完整顺序样本。','']
    (OUT/'cases.md').write_text('\n'.join(lines))


def paired(files,output):
    rr=[r for f in files for r in rows(f)];by=collections.defaultdict(dict)
    for r in rr:
        if r['status']!='complete':continue
        key=(r['seed'],r.get('rule','search'))
        assert r['variant'] not in by[key],('duplicate result',key,r['variant'])
        by[key][r['variant']]=r
    results=[]
    variants=sorted(set(r['variant'] for r in rr)-{'base'})
    for variant in variants:
        for rule in sorted(set(k[1] for k in by)):
            pairs=[(v['base'],v[variant]) for k,v in by.items() if k[1]==rule and 'base' in v and variant in v]
            if not pairs:continue
            assert all(a['root']==b['root'] and a['rng']==b['rng'] for a,b in pairs),'different root/RNG'
            rescued=sum(not a['win'] and b['win'] for a,b in pairs);lost=sum(a['win'] and not b['win'] for a,b in pairs)
            delta=[int(b['win'])-int(a['win']) for a,b in pairs]
            sem=statistics.stdev(delta)/math.sqrt(len(delta)) if len(delta)>1 else 0
            rescue_ci=binomial_interval(rescued,len(pairs));loss_ci=binomial_interval(lost,len(pairs))
            result=dict(rule=rule,variant=variant,n=len(pairs),base_wins=sum(a['win'] for a,b in pairs),candidate_wins=sum(b['win'] for a,b in pairs),rescued=rescued,lost=lost,net=rescued-lost,
                        conditional_delta=mean(delta),conservative95=[rescue_ci[0]-loss_ci[1],rescue_ci[1]-loss_ci[0]],
                        interval_method='Bonferroni difference of 97.5% Clopper-Pearson intervals for rescue and loss; avoids zero-width intervals when no discordance is observed',
                        base_cpu=mean([a['cpu_seconds'] for a,b in pairs]),candidate_cpu=mean([b['cpu_seconds'] for a,b in pairs]),
                        rescued_seeds=[a['seed'] for a,b in pairs if not a['win'] and b['win']],lost_seeds=[a['seed'] for a,b in pairs if a['win'] and not b['win']])
            if rule=='search':
                weighted=0
                result['historical_strata']={}
                for historic,weight in [(True,.482),(False,.147)]:
                    strata=[int(b['win'])-int(a['win']) for a,b in pairs if a['recorded_win']==historic]
                    if strata:weighted+=weight*mean(strata)
                    result['historical_strata'][str(historic)]=dict(n=len(strata),rescued=strata.count(1),lost=strata.count(-1),whole_run_weight=weight)
                result['estimated_whole_run_delta']=weighted
            results.append(result)
    Path(output).write_text(json.dumps(results,indent=2));return results


def compose_gates(files,output):
    """Evaluate a visible-state budget rule; never select by outcome or search result."""
    rr=[r for f in files for r in rows(f)];by=collections.defaultdict(dict)
    for r in rr:by[r['seed']][r['variant']]=r
    state={r['seed']:r['heart'] for r in rows(OUT/'profiles.jsonl') if r['cohort']=='traj-c38' and r.get('heart')}
    derived=[]
    for seed,variants in by.items():
        if 'base' not in variants:continue
        h=state[seed];eligible=h['hp']<.8*h['max_hp']
        for name,parent in [('low160','h160'),('low320','h320')]:
            source=parent if eligible else 'base'
            if source not in variants:continue
            derived.append(dict(variants[source],variant=name,derived_from=source,budget_gate_hp=h['hp'],budget_gate_max_hp=h['max_hp']))
    Path(output).write_text(''.join(json.dumps(r)+'\n' for r in derived))


if __name__=='__main__':
    profile_report();cases_report()
