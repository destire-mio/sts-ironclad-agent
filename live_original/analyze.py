"""Paired original/simulator outcomes. Faults never enter the win/loss denominator."""
import argparse,collections,gzip,json,lzma,math,statistics
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPORT=HERE.parents[1]/'scratchpad/parity/live-report.md'

def read(path):
    op=lzma.open if path.suffix=='.xz' else gzip.open if path.suffix=='.gz' else open
    with op(path,'rt') as f:return json.load(f)

def record_stream(directory,name):
    for suffix,op in [('.jsonl.xz',lzma.open),('.jsonl.gz',gzip.open)]:
        p=directory/(name+suffix)
        if p.exists():
            with op(p,'rt') as f:
                for line in f:yield json.loads(line)['data']
            return
    pattern={'steps':'step-*.json.gz','decisions':'decision-*.json.gz','plans':'plan-*.json'}[name]
    for p in sorted(directory.glob(pattern)):yield read(p)

def family(d):
    paths=[v['path'] for v in d['differences']]
    if all(p.startswith('/card_identity/') for p in paths):return '卡牌身份映射'
    if all(p.startswith(('/run/rng/aiRng/','/run/rng/monsterHpRng/')) for p in paths):return '局外战斗RNG重置时点'
    if d['floor']==0 and all(p.startswith('/run/rewards/') for p in paths):return '涅奥奖励界面表示'
    if any(p.startswith('/run/') for p in paths):
        if any(p.startswith(('/run/hp','/run/gold','/run/deck','/run/relic','/run/potion')) for p in paths):return '局外资源或界面阶段'
        if any(p.startswith('/run/rewards') for p in paths):return '奖励生成'
        if any('/rng/' in p for p in paths):return '局外随机流'
        return '局外界面或路线'
    if any('/piles/' in p for p in paths):return '战斗牌堆状态或顺序'
    if any('/rng/' in p for p in paths):return '战斗随机流'
    return '战斗状态'

def fault_context(directory, result):
    if result['status']!='fault':return None
    path=directory/'fault-view.json.gz'
    if not path.exists():return dict(kind='启动或外部执行故障')
    v=read(path);g=v['game'];screen=g['screen_type']
    relics=[r['id'] for r in g['relics']]
    event=g['screen_state'].get('event_id');error=result.get('error','')
    kind='尚未分类的桥接故障'
    if screen=='CARD_REWARD' and 'Toolbox' in relics and 'pending Java selection' in error:
        kind='工具箱战斗选牌队列无法导入'
    elif screen=='HAND_SELECT' and 'Gambling Chip' in relics:
        kind='赌博筹码开场换牌队列无法导入'
    elif screen=='HAND_SELECT' and g['screen_state'].get('selected') and 'Invalid command: choose' in error:
        kind='连续选牌间缺少确认命令（后续修复）'
    elif 'selection card has no unique original identity' in error:
        kind='战斗选牌身份映射失败'
    elif event in ('FaceTrader','Winding Halls'):
        kind='事件开场对白未确认（后续修复）'
    elif event=='WeMeetAgain':
        kind='再次相遇事件禁用选项映射（后续修复）'
    elif event=='Match and Keep!':
        kind='对对碰棋盘及已翻牌记忆未支持'
    elif event=='Wheel of Change' and 'missing GameContext continuation' in error:
        kind='变化大转盘事件续接状态缺失'
    elif event=='The Joust' and 'missing GameContext continuation' in error:
        kind='长枪决斗事件续接状态缺失'
    elif 'bowl' in error.lower():
        kind='歌唱碗命令翻译（后续修复）'
    return dict(kind=kind,floor=g['floor'],screen=screen,event=event,relics=relics)

def wilson(w,n):
    if not n:return None
    z=1.959963984540054;p=w/n;a=1+z*z/n
    center=(p+z*z/(2*n))/a;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/a
    return [center-half,center+half]

def discordant_interval(k,n):
    """97.5% Clopper-Pearson; two categories give a simultaneous 95% bound."""
    alpha=.0125
    def cdf(k,p):return sum(math.comb(n,j)*p**j*(1-p)**(n-j) for j in range(k+1))
    def solve(k,target):
        lo,hi=0.,1.
        for _ in range(60):
            mid=(lo+hi)/2
            if cdf(k,mid)>target:lo=mid
            else:hi=mid
        return (lo+hi)/2
    return [0. if k==0 else solve(k-1,1-alpha),1. if k==n else solve(k,alpha)]

def paired(rows,key='cloud'):
    valid=[r for r in rows if r['original_status'] in ('win','loss','act3_only') and r.get(key,{}).get('status') in ('heart_win','death','act3_without_heart')]
    n=len(valid);both=sum(r['original_win'] and r[key]['win'] for r in valid)
    only_o=sum(r['original_win'] and not r[key]['win'] for r in valid)
    only_s=sum(not r['original_win'] and r[key]['win'] for r in valid)
    w=both+only_o;v=both+only_s;delta=(w-v)/n if n else None
    # Bound the two discordant categories; remains nondegenerate at zero disagreements.
    pos=discordant_interval(only_o,n) if n else None
    neg=discordant_interval(only_s,n) if n else None
    return dict(n=n,original_wins=w,simulator_wins=v,original_win_rate=w/n if n else None,
        simulator_win_rate=v/n if n else None,original_wilson_95=wilson(w,n),simulator_wilson_95=wilson(v,n),
        difference=delta,difference_95=[pos[0]-neg[1],pos[1]-neg[0]] if n else None,
        difference_interval_method='conservative exact: Bonferroni Clopper-Pearson bounds on paired discordant categories',
        both_win=both,both_loss=n-both-only_o-only_s,original_only_win=only_o,simulator_only_win=only_s,
        outcome_agreement=(n-only_o-only_s)/n if n else None,
        terminal_floor_agreement=sum(r['original_floor']==r[key]['floor'] and r['original_win']==r[key]['win'] for r in valid))

def main():
    p=argparse.ArgumentParser();p.add_argument('--report',action='store_true');args=p.parse_args()
    cloud={r['seed']:r for r in read(HERE/'cloud-reference.json')['rows']}
    local={r['seed']:r for r in (json.loads(x) for x in (HERE/'simulator/results.jsonl').read_text().splitlines())}
    diagnostics=read(HERE/'simulator/diagnostic-seeds.json')
    reconstructed=read(HERE/'import-count-reconstruction.json')
    rows=[];types=collections.Counter();faults=collections.Counter();fault_mechanisms=collections.Counter()
    for result in [*sorted((HERE/'pilot').glob('*/result.json')),*sorted((HERE/'cohort').glob('*/result.json'))]:
        d=read(result);seed=d['seed'];directory=result.parent
        if d['status']=='running':continue
        floor=d.get('floor');act=d.get('act')
        if floor is None and (directory/'fault-view.json.gz').exists():
            game=read(directory/'fault-view.json.gz')['game'];floor=game['floor'];act=game['act']
        differences=d.get('divergences',[]);ft=[family(r) for r in differences];types.update(ft)
        if d['status']=='fault':faults[d.get('error','unknown')]+=1
        context=fault_context(directory,d)
        if context:fault_mechanisms[context['kind']]+=1
        imports=d.get('synchronization_count')
        imports_exact=imports is not None
        imports_method='runtime counter'
        if imports is None:
            recovered=reconstructed[str(seed)]
            imports=recovered['synchronization_count'];imports_exact=True
            imports_method=recovered['method']
        plans=d.get('combat_state_imports',reconstructed.get(str(seed),{}).get('combat_state_imports'))
        replans=plans-sum('plan' in b for b in d.get('battles',[]))
        rows.append(dict(seed=seed,original_status=d['status'],original_win=d['status']=='win',original_floor=floor,
            act=act,cloud={k:cloud[seed][k] for k in ('status','win','floor')},
            mac={k:local[seed][k] for k in ('status','win','floor')} if seed in local else None,
            mac_selection='outcome-selected diagnostic' if str(seed) in diagnostics else 'interrupted initial control batch' if seed in local else None,
            first_divergence=dict(floor=differences[0]['floor'],kind=ft[0],step=differences[0]['step']) if differences else None,
            divergence_count=len(differences),divergence_types=dict(collections.Counter(ft)),
            synchronization_count=imports,synchronization_exact=imports_exact,synchronization_method=imports_method,
            combat_replans=replans,combat_resynchronizations=d.get('resynchronizations',0),
            seconds=d.get('seconds'),error=d.get('error'),fault_context=context,evidence=str(directory)))
    rows.sort(key=lambda r:r['seed'])
    (HERE/'per-game.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    table=['首个分歧指导入原版状态后的单步模拟预测与 Java 观测差异，含界面和状态表示差异；不代表两条独立整局轨迹首次分叉。同步次数为 GameContext 与 BattleContext 的导入次数，含正常决策同步。秒数为该局执行耗时，故障不计入胜负分母。',
           '', '种子 | 原版终局/层 | c23终局/层 | 首个分歧 | 同步次数 | 秒 | 错误',
           '--- | --- | --- | --- | ---: | ---: | ---']
    labels={'win':'心脏胜','loss':'死亡','act3_only':'第三幕结束','fault':'无法继续','heart_win':'心脏胜','death':'死亡'}
    for r in rows:
        f=r['first_divergence'];first=f"{f['floor']}层：{f['kind']}" if f else '未记录'
        table.append(f"{r['seed']} | {labels[r['original_status']]}/{r['original_floor']} | "
            f"{labels.get(r['cloud']['status'],r['cloud']['status'])}/{r['cloud']['floor']} | {first} | "
            f"{r['synchronization_count']} | {r['seconds']:.1f} | {(r['error'] or '').replace('|','/')}" )
    (HERE/'per-game.md').write_text('\n'.join(table)+'\n')
    stats=dict(attempted=len(rows),completed=sum(r['original_status'] in ('win','loss','act3_only') for r in rows),
        unable=sum(r['original_status']=='fault' for r in rows),cloud_all_100_wins=sum(r['win'] for r in cloud.values()),
        paired_cloud=paired(rows),paired_mac=paired([r for r in rows if r['mac'] and str(r['seed']) not in diagnostics],key='mac'),
        divergence_types=dict(types),fault_types=dict(faults),fault_mechanisms=dict(fault_mechanisms),rows=rows)
    known_wins=sum(r['original_win'] for r in rows)
    stats['assigned_original_win_rate_bounds']=[known_wins/100,(known_wins+100-stats['completed'])/100]
    stats['unattempted_or_running']=100-len(rows)
    control={seed:r for seed,r in local.items() if str(seed) not in diagnostics}
    stats['mac_simulator_finished']=len(local)
    stats['mac_control_finished']=len(control)
    stats['mac_control_same_win_and_floor_as_cloud']=sum(
        (r['win'],r['floor'])==(cloud[s]['win'],cloud[s]['floor']) for s,r in control.items())
    stats['mac_control_note']='Initial control batch stopped for resource pressure; unfinished runs excluded. These completion-selected rows are descriptive checks, not the primary paired sample.'
    stats['mac_diagnostics']=diagnostics
    (HERE/'summary.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
    print(json.dumps({k:v for k,v in stats.items() if k not in ('rows','fault_types')},ensure_ascii=False))
    if args.report:
        a=stats['paired_cloud'];n=a['n'];pct=lambda x:f'{100*x:.1f}%';pp=lambda x:f'{100*x:+.1f}'
        content=f'''原版完成 {n} 局，心脏胜率 {a['original_wins']}/{n}＝{pct(a['original_win_rate'])}；对应 c23 同种子模拟器为 {a['simulator_wins']}/{n}＝{pct(a['simulator_win_rate'])}。原版减模拟器为 {pp(a['difference'])} 个百分点，配对 95% 区间为 [{pp(a['difference_95'][0])}, {pp(a['difference_95'][1])}] 个百分点。该区间用于判断差距；样本量与无法继续的局限制总体推断。

尝试 {stats['attempted']} 个种子，无法继续 {stats['unable']} 局，故障不计胜负。种子从 3900002000 起，目标 100。云上前 100 局为 {stats['cloud_all_100_wins']} 胜；配对比较使用原版完成的相同种子。

胜负一致率 {pct(a['outcome_agreement'])}：两边赢 {a['both_win']} 局，两边输 {a['both_loss']} 局；原版独赢 {a['original_only_win']} 局，模拟器独赢 {a['simulator_only_win']} 局。胜负及终局楼层相同 {a['terminal_floor_agreement']}/{n}。

执行本机原版 Java JAR，含 ModTheSpire、BaseMod、CommunicationMod 与无头逻辑/导出模组。采用指定 P300 策略和 combat4；游戏状态以 Java 为准，导入真实战斗 RNG，分歧后从当前状态继续。读档、换种子、同一状态重复搜索选结果次数为 0。原版与模拟器采用每层 45 秒的规则时间输入。

策略、模型、配置和价值表与云上输入核对相同；战斗入口通过普通战与 Boss 战的动作/搜索量对照，147 次局外选择与生产轨迹相同。记录到的主要分歧类型为：{'；'.join(f'{k} {v} 次' for k,v in types.most_common(5))}。这些计数包含界面阶段与身份表示差异，不能作为胜负差距的因果证据。

逐局结果：[per-game.jsonl]({HERE/'per-game.jsonl'})；完整统计：[summary.json]({HERE/'summary.json'})；每局原版命令、前后状态、RNG、搜索计划及清理记录保存在 [live]({HERE})。批次支持续跑：使用项目 Python 3.12 执行 `ironclad-alignment/live/batch.py --games 100 --workers 2`，完成或故障种子不重复执行。
'''
        REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(content)

if __name__=='__main__':main()
