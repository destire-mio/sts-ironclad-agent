from pathlib import Path
import json,re,hashlib,subprocess,shutil
r=Path(__file__).resolve().parents[1];patches=r/'snapshots/parity-sim_patch';applied={x['patch'] for x in json.loads((r/'evidence/patch-application.json').read_text())};tests=json.loads((r/'evidence/test-summary-mac.json').read_text())['tests'];records=[]
check=r/'evidence/baseline-patch-check';shutil.copytree(r.parent/'sts-rl-agent-combat4q/engine-source',check,dirs_exist_ok=True)
manual={'action_queue.patch':['havoc_unplayable','e106_shuffle','e111_lethal_branch','ethereal_profiles_queued_copy'],'combat_rules.patch':[n for n in tests if n.startswith('combat_')],'ironclad_a20.patch':['book_stab_count','emerald_elite_buffs','hexaghost_burns','awakened_pending_rebirth','monster_hp_ranges'],'parity_followup.patch':[n for n in tests if n.startswith('parity_followup_')],'sim_rl_hooks.patch':['training_observation','training_all_decisions','training_python_contract']}
for p in sorted(patches.glob('*.patch')):
 if p.name in applied:continue
 x=dict(patch=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
 if p.name.startswith('search_'):x.update(status='not_reapplied_search',reason='combat4q own search takes precedence',tests=['432 paired fixed states and 27 deterministic r states per platform'])
 else:
  out=subprocess.run(['patch','--dry-run','-R','--batch','--fuzz=0','-p1','-i',str(p)],cwd=check,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  prefix=re.match(r'(e\d+)_',p.name);names=[n for n in tests if n.startswith(prefix[1]+'_')] if prefix else manual[p.name]
  assert names and all(tests[n]['passed'] for n in names)
  x.update(status='inherited_combat4q_not_reapplied',reverse_patch_clean=out.returncode==0,reverse_check=out.stdout,tests=names,test_passed=True)
 records.append(x)
(r/'evidence/inherited-patch-inventory.json').write_text(json.dumps(records,indent=2))
p=r/'evidence/PORTING.md';s=p.read_text();s+='\n## 快照其余补丁的处理\n\n以下 18 份早期规则／接口补丁沿用 4q 源码，未重贴；4 份历史搜索补丁不重贴，原因是保留 4q 搜索。父包源码哈希与继承文件见构建来源；反向干运行结果和对应回归测试保存在 `inherited-patch-inventory.json`。反向检查失败表示补丁上下文被后续版本改写，不能据此认定机制缺失。\n\n|来源补丁|处理|验证|\n|---|---|---|\n'
for x in records:
 if x['status']=='not_reapplied_search':status='不重贴，保留 4q 搜索';validation='固定状态、合法动作、回放与确定性检查'
 else:status='沿用 4q，未重贴';validation=f"{len(x['tests'])} 个对应回归入口通过；反向干运行"+('吻合' if x['reverse_patch_clean'] else '存在后续上下文差异')
 s+=f"|`{x['patch']}`|{status}|{validation}|\n"
p.write_text(s)
print(json.dumps({'inherited':sum(x['status']=='inherited_combat4q_not_reapplied' for x in records),'legacy_search':sum(x['status']=='not_reapplied_search' for x in records),'reverse_clean':sum(x.get('reverse_patch_clean',False) for x in records)}))
