from pathlib import Path
import json,xml.etree.ElementTree as ET,hashlib
r=Path(__file__).resolve().parents[1]
tests={}
for path in ['evidence/ctest-mac.xml','evidence/ctest-mac-missing-fixtures.xml']:
 for t in ET.parse(r/path).getroot().iter('testcase'):
  tests[t.attrib['name']]={'passed':t.find('failure') is None,'seconds':float(t.attrib.get('time',0))}
assert len(tests)==469 and all(x['passed'] for x in tests.values())
patches=json.loads((r/'evidence/patch-application.json').read_text());records=[]
labels=['疼痛撕裂／虚空扣能量','群攻伤害冻结／鸟面瓮顺序','消耗能力顺序／红头骨队列','抽牌能力顺序／红头骨激活状态','撕裂／残暴入队顺序','负力量突破极限／多重暴走／吸血／旋风斩／手动弃牌','斗技场激怒','虚无消耗与洗牌模式','巩固／幽灵铠甲消耗回调','斗技场 RNG 延续','瓶装候选顺序','固有／瓶装开局抽牌','天体仪小牌组','昆虫标本不抬高残血','茶具／小花／香炉／哀嚎生命周期','遗物默认计数','商店待领奖励恢复','商店延迟删牌','商店初始界面共享 RNG','药水／瓶装／蛋／会员卡 RNG','删牌／粒子共享 RNG','药水鼎／星系仪奖励 RNG','华夫饼／多利之镜获得与回血时序','磨刀石／战纹升级时序','卡牌获得遗物回调／御守','商店点击动作域','奖励点击动作域','百年积木／符文立方体获得顺序','百年积木恢复私有状态','发掘选牌与暂存牌序']
prefixes=['pain_void','aoe_urn','exhaust_skull','draw_skull','rupture_brutality','limit_backlog','colosseum_enrage','ethereal_profiles','ethereal_overrides','colosseum_rng','bottle_choice','innate_opening','astrolabe_small','preserved_insect','relic_counters','relic_defaults','shop_rewards','shop_purge','shop_shared_rng','shop_other_rng','shop_purge_rng','shop_reward_rng','shop_obtain_rng','shop_upgrade_rng','card_obtain_callbacks','shop_click_domain','reward_click_domain','hp_loss_relic_order','centennial_restore','exhume_selection']
lines=['# combat4r 移植和验证清单','','30 份增量补丁均以 `patch -p1 --fuzz=0` 应用；规则补丁和可选 RNG／点击域补丁无跳过。来源为本目录 snapshots/parity-sim_patch 的哈希快照。原版捕获回放保留来源的 coverage_gap 标记，表示被比较字段吻合，不代表穷举一致性。','','|修复|来源补丁|处理|本次 Mac 验证|','|---|---|---|---|']
for p,label,prefix in zip(patches,labels,prefixes):
 matches=[n for n in tests if n.startswith(prefix+'_')]
 assert matches,prefix
 rec=dict(**p,description=label,tests=matches,test_passed=all(tests[n]['passed'] for n in matches));records.append(rec)
 lines.append(f'|{label}|`{p["patch"]}`|移植；零模糊|{len(matches)}/{len(matches)} 测试入口通过|')
lines+=['','卡牌审计八项：前七项由上述依赖完整的机制补丁修复，另改 Nemesis 灼伤阈值 `asc3 → asc18`。审计原始 50 个机制探针与 62 个状态探针、284 项数值检查在 Mac／ARM Linux 通过。原版反例通过上述 Python 捕获回放入口验证。','','狂宴终局评分：胜利时增加 `100 × max(0, terminal.maxHp − combatEntry.maxHp)`。当前 HP 每点原本值 100 分，所以每点新上限额外折合 1 HP；即时回血沿用原 HP 项，未重复算作上限即时收益。假设是未来恢复和伤害容忍能力值 1 HP，未声称由整局数据拟合。逃跑、死亡、截断无奖励；重规划和子树保留使用本场初始上限。9 组固定终局对照覆盖 0.5／1／2 HP 等价权重和 0／2／4 HP 代价，结果见 probes/score_contract-r.jsonl。','','combat4q 的搜索、预算、目标选择、药水评分和终局删药流程保留；删药等价检查补入新增加的 endTurnShuffle 模式与 48 位 Java RNG 状态。快照中的历史 `search_*.patch` 不重贴，避免覆盖 4q 的自有搜索；其余早期规则补丁沿用 4q 基线并由既有回归套件检查。','','Mac 原 CTest 清单 469 个入口：首轮 464 通过，5 个因外围测试文件未复制而无法执行；补齐只读来源的依赖快照后，5 个定向复测通过。两份原始结果均保留，没有删除失败记录。']
(r/'evidence/port-inventory.json').write_text(json.dumps(records,indent=2));(r/'evidence/test-summary-mac.json').write_text(json.dumps({'test_entries':len(tests),'passed':sum(x['passed'] for x in tests.values()),'initial_missing_fixture_entries':5,'focused_rerun_passed':5,'tests':tests},indent=2));(r/'evidence/PORTING.md').write_text('\n'.join(lines)+'\n')
print('inventory',len(records),'tests',len(tests))
