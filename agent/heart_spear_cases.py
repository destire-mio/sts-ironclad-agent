"""Replay the four discordant Spear pairs to describe their Heart entries."""
import gzip
import json
from heart_research import OUT, C, S, root_at, replay_battle, game_info, combat_info
from heart_research_report import rows, table


def main():
    results = rows(OUT/'spear-results.jsonl')
    entries = []
    for row in results:
        if row['seed'] not in (3900012719, 3900012494, 3900012154, 3900012688):
            continue
        _, _, g, _ = root_at(row['path'], row['step'])
        suffix = C.read_run(row['suffix_trace'])
        for item in suffix['prefix']:
            C.H.clock_input(g, C.CONFIG)
            if item['kind'] == 'battle':
                heart = g.encounter.name == 'THE_HEART'
                if heart:
                    b = S.BattleContext(); b.init(g)
                    entry = dict(seed=row['seed'], variant=row['variant'], win=row['win'],
                                 root=C.H.fingerprint(g), rng=dict(g.rng_states),
                                 state=game_info(g), initial=combat_info(b))
                    entries.append(entry)
                trace = replay_battle(g, item, heart)
                if heart:
                    path = OUT/f'spear-case-{row["seed"]}-{row["variant"]}.json.gz'
                    with gzip.open(path, 'wt') as handle:
                        json.dump(trace, handle)
                    entry['trace'] = str(path)
            else:
                action = S.GameAction(item['action'] & 0xffffffff)
                assert action.is_valid(g)
                action.execute(g)
        assert (C.H.terminal(g) == 'heart_win') == row['win']
    assert len(entries) == 8
    (OUT/'spear-case-entries.json').write_text(json.dumps(entries, indent=2))
    lines = ['# 盾矛预算改变后的四个胜负分歧', '',
             '列出全部3个救回与1个损失，不按故事好坏挑选。两分支从同一盾矛入口开始；后续HP、药水、遗物计数、RNG等可以随合法动作改变。', '']
    data=[]
    for seed in (3900012719, 3900012494, 3900012154, 3900012688):
        pair=[r for r in entries if r['seed']==seed]
        for r in sorted(pair,key=lambda r:r['variant']):
            data.append([seed,r['variant'],r['state']['hp'],r['state']['max_hp'],
                         ', '.join(r['state']['potion_names']),r['win']])
        base=next(r for r in pair if r['variant']=='base')
        candidate=next(r for r in pair if r['variant']=='candidate')
        lines += [f'- {seed}：Heart入口RNG相同={base["rng"]==candidate["rng"]}；记录字段指纹相同={base["root"]==candidate["root"]}；首手相同={base["initial"]["hand"]==candidate["initial"]["hand"]}。']
    lines += ['',table(['seed','策略','Heart战前HP','最大HP','药水','Heart胜'],data),'',
              '2688从28HP提高到50HP却由胜转负；不能把入场HP作为胜负的充分条件。2719两线都是126HP、相同药水数量，终局仍不同；完整入口字段与首手见 spear-case-entries.json。收益来自整条合法分叉的终局，不能全部归因于多保住几滴血。']
    (OUT/'spear-cases.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps([{k:r[k] for k in ('seed','variant','win','root')} for r in entries]))


if __name__ == '__main__':
    main()
