"""Audit completed natural runs and produce a Chinese, evidence-bound report."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sim_patch.parity.core import read_json,write_json,sha256

LABELS={
 'terminal':('终局预测不同',4), 'hp_shortfall':('本步血量低于预测',3),
 'run_resources':('牌组、奖励、遗物或资源',3), 'combat_state':('战斗 RNG、抽牌、意图或能力',2),
 'exhaust_order':('虚无牌消耗顺序',1), 'outside_rng':('局外 RNG',1),
 'identity':('同牌面卡牌身份关系',0), 'idle_floor_rng':('非战斗楼层重置 RNG',0),
 'other':('其他状态字段',1)}


def classify(divergence,row):
    categories=set();hp=0
    old,new=row['before']['game'],row['after']['game']
    for d in divergence['differences']:
        path=d['path']
        if path=='/outcome':categories.add('terminal')
        elif path in ('/player/hp','/run/hp') and isinstance(d.get('original'),(int,float)):
            shortfall=max(0,d['simulator']-d['original']);hp+=shortfall
            categories.add('hp_shortfall' if shortfall else 'other')
        elif path.startswith('/card_identity/'):categories.add('identity')
        elif path.startswith('/run/rng/'):
            stream=path.split('/')[3]
            if stream in ('aiRng','monsterHpRng') and old['floor']!=new['floor'] and new['room_phase']!='COMBAT':
                categories.add('idle_floor_rng')
            else:categories.add('outside_rng')
        elif path.startswith('/piles/exhaust_pile/'):
            comparison=row['comparison'];e=comparison.get('expected',{}).get('piles',{}).get('exhaust_pile',[])
            a=comparison.get('actual',{}).get('piles',{}).get('exhaust_pile',[])
            same=Counter(json.dumps(c,sort_keys=True) for c in e)==Counter(json.dumps(c,sort_keys=True) for c in a)
            categories.add('exhaust_order' if same and e else 'combat_state')
        elif path.startswith(('/run/deck','/run/rewards','/run/relics','/run/potions','/run/gold','/run/keys','/run/boss_relics')):
            categories.add('run_resources')
        elif path.startswith(('/piles/','/rng/','/monsters','/legacy/','/player/','/legal_actions','/card_playability')):
            categories.add('combat_state')
        else:categories.add('other')
    return categories,hp


def audit(directories,baseline=None):
    accepted={};attempts=[]
    for directory in directories:
        for path in sorted(directory.glob('*/result.json')):
            result=read_json(path);seed=result['seed'];terminal=result.get('completed_natural_runs')==1 and result['status'] in ('win','loss','act3_only')
            attempts.append(dict(seed=seed,status=result['status'],terminal=terminal,path=str(path),sha256=sha256(path)))
            if terminal:accepted[seed]=(path,result)
    rows=[];frequencies=Counter();affected=defaultdict(set);evidence=[]
    for seed,(path,r) in sorted(accepted.items()):
        counts=Counter();hp=0
        for d in r['divergences']:
            step=path.parent/f"step-{d['step']:05}.json.gz";record=read_json(step)
            categories,shortfall=classify(d,record);counts.update(categories);hp+=shortfall
            for c in categories:affected[c].add(seed)
            evidence.append(dict(seed=seed,step=d['step'],floor=d['floor'],command=d['command'],
                categories=sorted(categories),hp_shortfall=shortfall,cards=d['cards'],monsters=d['monsters'],relics=d['relics'],
                path=str(step),sha256=sha256(step),differences=d['differences']))
        frequencies.update(counts)
        impact=('终局预测不同，胜负因果待复盘' if counts['terminal'] else
                '存在血量代价，胜负因果未验证' if hp else
                '影响计划或资源，胜负因果未验证' if counts['combat_state'] or counts['run_resources'] else
                '被测资源未检出损失，胜负因果未验证')
        b=read_json(baseline/f'{seed}.json') if baseline and (baseline/f'{seed}.json').exists() else None
        rows.append(dict(seed=seed,status=r['status'],floor=r['floor'],act=r['act'],steps=r['steps'],
            divergences=len(r['divergences']),types=dict(counts),save_load_count=r['save_load_count'],
            resynchronizations=r['resynchronizations'],hp_shortfall=hp,impact=impact,
            baseline_status=b['status'] if b else None,path=str(path),sha256=sha256(path),
            capture_code_sha256=r['capture_code_sha256'],runtime_manifest_sha256=r['runtime_manifest_sha256']))
    rankings=sorted([dict(type=k,label=LABELS[k][0],events=v,runs=len(affected[k]),
                         potential_impact_grade=LABELS[k][1],priority=v*LABELS[k][1]) for k,v in frequencies.items()],
                    key=lambda r:(-r['priority'],-r['events']))
    return dict(completed=len(rows),wins=sum(r['status']=='win' for r in rows),
        losses=sum(r['status']=='loss' for r in rows),act3_only=sum(r['status']=='act3_only' for r in rows),
        commands=sum(r['steps'] for r in rows),divergences=sum(r['divergences'] for r in rows),
        save_load_count=sum(r['save_load_count'] for r in rows),runs=rows,ranking=rankings,attempts=attempts,evidence=evidence)


def markdown(data):
    n=data['completed'];w=data['wins']
    lines=['# 原版自然局与模拟器差异：逐动作统计','',
        f'原版 Java 规则运行完成 {n} 局：心脏胜局 {w}，死亡 {data["losses"]}，第三幕结束 {data["act3_only"]}。共 {data["commands"]} 条原版命令，{data["divergences"]} 个分歧检查点，读档 {data["save_load_count"]} 次。',
        '', '运行环境含 BaseMod、CommunicationMod、SpireLabLogic 与状态审计模组。它执行本机安装的原版 Java 规则，不能称为无 Mod 客户端测试。故障、诊断夹具和中断记录不进入胜负分母。',
        '', '每行使用该种子的末个完成记录；原始尝试、版本哈希和分歧原文保留在配套 JSON 中。同种子纯模拟器结果供对照，路线、奖励与时间输入可能分叉，不能把两侧胜负不同归因于某一个规则。',
        '', '| 种子 | 原版结果/楼层 | 模拟器结果 | 分歧检查点 | 类型及次数 | SL | 影响分类 |',
        '|---|---|---|---:|---|---:|---|']
    for r in data['runs']:
        labels='；'.join(f'{LABELS[k][0]} {v}' for k,v in r['types'].items()) or '无'
        lines.append(f'| {r["seed"]} | {r["status"]} / {r["floor"]} | {r["baseline_status"] or "未采集"} | {r["divergences"]} | {labels} | {r["save_load_count"]} | {r["impact"]} |')
    lines+=['','## 修复优先级','',
        '同一检查点可以含多种差异。频率按“出现该类型的检查点数”统计，避免把一个 RNG 的种子与计数拆成三次。影响等级是排查优先级：0 为身份或暂存状态，1 为顺序或局外随机流，2 为战斗计划，3 为资源，4 为终局。等级不是实测胜率损失；排序为频率 × 等级。',
        '', '| 差异类型 | 检查点 | 涉及局数 | 影响等级 | 乘积 |','|---|---:|---:|---:|---:|']
    for r in data['ranking']:lines.append(f'| {r["label"]} | {r["events"]} | {r["runs"]} | {r["potential_impact_grade"]} | {r["priority"]} |')
    lines+=['','## 覆盖边界','',
        '每条命令保存原版前后状态与 16 个持久 RNG 流。战斗比较玩家、牌堆及顺序、怪物、意图、能力、遗物计数、合法输入和 6 条战斗 RNG；局外比较血量、金币、牌组、遗物、药水、钥匙及原生引擎持有的游戏随机流，后续版本补充奖励与地图。界面确认、待选牌过程和未建模私有字段按缺口记录。',
        '', 'MathUtils 与 Collections 共享随机源有完整导出与恢复验证；未来状态未由模拟器逐条预测。native 缺少持久 mapRng 计数。上述缺口使“没有记录分歧”不能解释为完整状态一致。',
        '', '全量动作与状态日志、运行版本、故障记录以及原版存档保存在工作树 runs/；配套 JSON 对每份纳入结果和分歧日志记录 SHA-256。JAR、游戏资源及存档不随 Git 分发。','']
    return '\n'.join(lines)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cohort',type=Path,action='append',required=True);p.add_argument('--baseline',type=Path)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args();d=audit(a.cohort,a.baseline)
    write_json(a.out.with_suffix('.json'),d);a.out.with_suffix('.md').write_text(markdown(d))
    print({k:d[k] for k in ('completed','wins','losses','commands','divergences','save_load_count')})
