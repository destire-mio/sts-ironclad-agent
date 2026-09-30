"""Build a source-only ARM update payload; never include Mac native modules."""
from pathlib import Path
import difflib, hashlib, json, shutil, tarfile

r = Path(__file__).resolve().parents[1]
out = r/'cloud-update'; out.mkdir(exist_ok=True)
bundle = out/'combat4r-victory-hp-update'; bundle.mkdir(exist_ok=True)
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
native = ['engine-source/include/combat/VictoryHp.h', 'engine-source/include/combat/BattleContext.h', 'engine-source/src/combat/BattleContext.cpp', 'engine-source/src/sim/search/BattleScumSearcher2.cpp', 'agent/fightsim.cpp']
files = native + ['package.py'] + ['tools/'+name for name in [
    'rebuild_victory_hp.py', 'build_probes.py', 'build_extra.py', 'check_probes.py', 'paired_io.cpp',
    'score_contract.cpp', 'victory_hp_contract.cpp', 'plan_victory_hp.py', 'run_victory_hp.py',
    'verify_victory_hp.py', 'audit_victory_hp_feed.py', 'summarize_victory_hp.py',
    'smoke_victory_hp.py', 'audit_victory_hp.py', 'report_victory_hp.py',
]]
for n in files:
    p = bundle/'payload'/n; p.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(r/n, p)
shutil.copy2(r/'tools/apply_victory_hp_cloud.py', bundle/'apply_victory_hp_cloud.py')
manifest = dict(revision='victory-hp-20260929', expected_cloud_identity=json.loads((r/'evidence/linux-final/final-audit.json').read_text())['runtime_identity'], previous_cpp_sha256=json.loads((r/'evidence/expected-cpp-sha256.json').read_text()), payload_sha256={n:sha(r/n) for n in files}, launcher_sha256=sha(bundle/'apply_victory_hp_cloud.py'), mac_identity=json.loads((r/'runtime-delivery/identity.json').read_text()), cloud_execution_status='pending: current session SSH network sandbox denies connection')
(bundle/'update-manifest.json').write_text(json.dumps(manifest, indent=2))
readme = '''# combat4r 战后 HP：ARM 更新材料

当前状态：Mac 构建与验证见上级 report.md。当前会话 SSH 返回 Operation not permitted，ARM 更新脚本尚未在云端执行。

归档包含源码和验证脚本，不含 Mac 二进制。云端目标为 ~/sts/combat4r。使用云端现有、含 torch/numpy 且 ABI 与 combat4r 匹配的 Python 环境执行：

```sh
tar -xzf combat4r-victory-hp-update.tar.gz
python combat4r-victory-hp-update/apply_victory_hp_cloud.py --root ~/sts/combat4r
```

脚本校验旧包身份、89 个旧 C++ 文件、父运行包和载荷 SHA256；备份 combat4r；沿用现有 ARM 构建命令；打包；运行单元测试、432+2 固定状态、确定性/合法动作/战后与 RNG 回放；执行同 arms、种子 3000000000–3000000007 的 8 局冒烟；更新报告、构建哈希与证据归档。

进程继承至多 4 核的 CPU affinity，数值库 1 线程，编译顺序执行，测试最多 4 个计算进程，冒烟 1 个计算进程。脚本不终止进程，4q 和 v12/v13/v14/v15 保持只读。4q 使用同平台冻结的既有结果；新 4r 每状态一次主搜索。

若执行失败，日志与首轮结果保留，脚本拒绝覆盖已有备份与证据目录。按对应日志修复后接续缺失阶段，不删除结果或换种子重试。执行完成后，证据归档位于 ~/sts/combat4r/evidence/victory-hp/cloud-results.tar.gz。

本地检查范围为 Python 语法、归档成员和文件哈希；这些检查不等价于 ARM 构建及冒烟通过。
'''
(out/'README.md').write_text(readme); (bundle/'README.md').write_text(readme)
archive = out/'combat4r-victory-hp-update.tar.gz'
with tarfile.open(archive, 'w:gz', format=tarfile.PAX_FORMAT) as t:
    for p in sorted(bundle.rglob('*')):
        if p.is_file(): t.add(p, arcname=str(p.relative_to(out)), recursive=False)
with tarfile.open(archive) as t:
    for m in t.getmembers():
        assert m.isfile() and not Path(m.name).is_absolute() and '..' not in Path(m.name).parts
        assert not m.name.endswith('.so') and not Path(m.name).name.startswith('._')
    for n, h in manifest['payload_sha256'].items():
        assert hashlib.sha256(t.extractfile('combat4r-victory-hp-update/payload/'+n).read()).hexdigest() == h
for n in files+['tools/apply_victory_hp_cloud.py']:
    if n.endswith('.py'): compile((r/n).read_text(), n, 'exec')
(out/'SHA256SUMS').write_text(f"{sha(archive)}  {archive.name}\n{sha(bundle/'update-manifest.json')}  combat4r-victory-hp-update/update-manifest.json\n")
patch = []
with tarfile.open(r/'revisions/pre-victory-hp/previous-delivery.tar.gz') as old:
    for n in native:
        previous = [] if n.endswith('VictoryHp.h') else old.extractfile(n).read().decode().splitlines(keepends=True)
        patch.extend(difflib.unified_diff(previous, (r/n).read_text().splitlines(keepends=True), fromfile='/dev/null' if not previous else 'a/'+n, tofile='b/'+n))
(r/'evidence/victory-hp/source.patch').write_text(''.join(patch))
print(json.dumps(dict(archive=str(archive), sha256=sha(archive), bytes=archive.stat().st_size, payload_files=len(files), status='source-only; ARM execution pending')))
