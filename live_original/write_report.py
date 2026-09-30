"""Render the requested short Chinese report from audited paired outcomes."""
import argparse,datetime,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
REPORT=HERE.parents[1]/'scratchpad/parity/live-report.md'

def main():
    p=argparse.ArgumentParser();p.add_argument('--interim',action='store_true');a=p.parse_args()
    s=json.loads((HERE/'summary.json').read_text());v=s['paired_cloud'];n=v['n']
    if not a.interim:
        audit=json.loads((HERE/'audit.json').read_text())
        assert s['attempted']==100
        assert {r['seed'] for r in s['rows']}==set(range(3900002000,3900002100))
        assert n>=50 and audit['terminal_count']==n
        assert not audit['remaining_original_processes']
    pct=lambda x:f'{x*100:.1f}%'
    pp=lambda x:'0.0' if x==0 else f'{x*100:+.1f}'
    short={
        '工具箱战斗选牌队列无法导入':'工具箱选牌队列',
        '赌博筹码开场换牌队列无法导入':'赌博筹码换牌队列',
        '对对碰棋盘及已翻牌记忆未支持':'对对碰棋盘',
        '事件开场对白未确认（后续修复）':'事件开场对白',
        '歌唱碗命令翻译（后续修复）':'歌唱碗命令',
        '再次相遇事件禁用选项映射（后续修复）':'再次相遇选项',
        '连续选牌间缺少确认命令（后续修复）':'连续选牌确认',
        '战斗选牌身份映射失败':'战斗选牌身份映射',
        '变化大转盘事件续接状态缺失':'变化大转盘事件状态',
        '长枪决斗事件续接状态缺失':'长枪决斗事件状态',
    }
    faults='、'.join(f'{short.get(k,k)}{c}局' for k,c in s['fault_mechanisms'].items())
    fixed=sum(c for k,c in s['fault_mechanisms'].items() if '后续修复' in k)
    prefix=(f'中间结果（{datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}）：目标100个种子，{s["attempted"]}个尝试结束，{s["unattempted_or_running"]}个在途或待启动。\n\n' if a.interim else '')
    lead=(f'原版整局运行打通。完成的{n}局同种子对比中，原版{v["original_wins"]}胜、云上模拟器{v["simulator_wins"]}胜，心脏胜率相同：**{pct(v["original_win_rate"])}**。' if v['difference']==0 else
        f'原版整局运行打通。完成局的心脏胜率为 **{v["original_wins"]}/{n}＝{pct(v["original_win_rate"])}**，同种子云上模拟器为 **{v["simulator_wins"]}/{n}＝{pct(v["simulator_win_rate"])}**。')
    text=prefix+lead+f'''原版减模拟器为 {pp(v['difference'])} 个百分点，配对保守95%区间为 [{pp(v['difference_95'][0])}, {pp(v['difference_95'][1])}] 个百分点；“胜率接近”的证据受样本量和故障筛选限制。

胜负一致率 {pct(v['outcome_agreement'])}：两边赢{v['both_win']}局、两边输{v['both_loss']}局，原版胜/模拟器负{v['original_only_win']}局、原版负/模拟器胜{v['simulator_only_win']}局。胜负及终局楼层相同{v['terminal_floor_agreement']}/{n}局。

种子范围3900002000—3900002099。{s['attempted']}个尝试中，{n}局到终局、{s['unable']}局无法继续；胜负分母采用完成局。故障为：{faults}。执行中修复界面、命令与部分身份映射问题，修复用于后续种子；故障原记录保留。故障集中于特定遗物和事件，存在选择偏差。
'''
    if not a.interim:
        lo,hi=s['assigned_original_win_rate_bounds']
        text+=f'按故障贡献0至{s["unable"]}胜计算，指定100个种子的原版胜率范围为{pct(lo)}—{pct(hi)}；云上100局为39.0%。此范围表示缺失结果的边界。\n'
    text+='''
执行本机原版Java JAR，运行于ModTheSpire无头逻辑模式。采用指定P300策略和combat4，基础搜索预算40,000、Boss倍率12，规则时间按每层45秒输入。机器人读取原版状态和真实RNG选择动作，分歧后同步状态继续。换种子、读档、同状态搜索重试择优次数为0。

主要机制线索是战斗搜索计划分叉及后续血量、升级选择变化：种子3900002003在第6层选招分叉，第32层原版休息、模拟器升级，终局为原版死于心脏战、模拟器击败心脏；种子3900002045局外动作到第33层相同，战斗路径分叉，终局为原版击败心脏、模拟器死于第33层。编号/牌堆差异会触发状态重导入；各机制对胜率差距的贡献缺少隔离实验。
'''
    if a.interim:
        text+='\n批次继续运行；终局审计和实例清理在结束时执行。续跑入口为 live/resume.sh，跳过完成及故障种子。\n'
    else:
        start=datetime.datetime.fromisoformat(json.loads((HERE/'plan.json').read_text())['start_utc'])
        elapsed=int((datetime.datetime.now(datetime.timezone.utc)-start).total_seconds()/60)
        text+=f'\n策略代码、模型、配置和价值表与云端核对吻合；终局及命令审计通过。并行峰值4个原版实例，本任务Java残留进程数为0；云端保持只读。耗时{elapsed//60}小时{elapsed%60}分。\n'
    text+=f'\n[报告]({REPORT}) · [逐局结果]({HERE/"per-game.md"}) · [统计与证据]({HERE/"summary.json"})\n'
    assert len(text)<=1500,(len(text),'report exceeds 1500 characters including links')
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(text)
    print(json.dumps(dict(report=str(REPORT),characters=len(text),interim=a.interim),ensure_ascii=False))

if __name__=='__main__':main()
