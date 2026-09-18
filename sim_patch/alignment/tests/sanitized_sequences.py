"""macOS ASan launcher for framework Python and its isolated row processes.

Homebrew's bin/python launcher re-execs and strips DYLD_INSERT_LIBRARIES.
Use the framework executable for initial loading, then propagate it to children.
This runner changes interpreter startup only; the comparator is unchanged.
"""
from pathlib import Path
import json,os,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
FRAMEWORK=Path(sys.base_prefix)/'Resources/Python.app/Contents/MacOS/Python'
if not FRAMEWORK.exists():raise RuntimeError('macOS framework Python is required')
build=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'build-sanitized'
resource=subprocess.check_output(['clang','--print-resource-dir'],text=True).strip()
asan=Path(resource)/'lib/darwin/libclang_rt.asan_osx_dynamic.dylib'
bootstrap="import os,sys,runpy;sys.executable=os.environ['ALIGNMENT_FRAMEWORK_PYTHON'];os.environ['DYLD_INSERT_LIBRARIES']=os.environ['ALIGNMENT_ASAN_LIBRARY'];sys.argv=sys.argv[1:];sys.path.insert(0,os.path.dirname(sys.argv[0]));runpy.run_path(sys.argv[0],run_name='__main__')"
env={**os.environ,'ALIGNMENT_FRAMEWORK_PYTHON':str(FRAMEWORK),'ALIGNMENT_ASAN_LIBRARY':str(asan),'DYLD_INSERT_LIBRARIES':str(asan),'ASAN_OPTIONS':'detect_leaks=0','UBSAN_OPTIONS':'halt_on_error=1:print_stacktrace=1','ALIGNMENT_BUILD':str(build),'ALIGNMENT_STRICT':'1','ALIGNMENT_REPORT_DIR':str(build/'original-comparisons')}
results=[]
for name in ['original-repair-cards','original-repair-powers','original-repair-potions','original-repair-upgrades','original-repair-combinations','original-prior-sequences']:
 source=ROOT/'tests/fixtures'/(name+'.json.gz');cmd=[str(FRAMEWORK),'-c',bootstrap,str(ROOT/'tests/compare_sequences.py'),str(source),'--check']
 proc=subprocess.run(cmd,env=env);results.append({'fixture':name,'returncode':proc.returncode});print(name,proc.returncode,flush=True)
name='original-natural-trace'
proc=subprocess.run([str(FRAMEWORK),'-c',bootstrap,str(ROOT/'tests/replay_trace.py'),str(ROOT/'tests/fixtures'/(name+'.json.gz'))],env=env)
results.append({'fixture':name,'returncode':proc.returncode});print(name,proc.returncode,flush=True)
(build/'sanitized-sequences.json').write_text(json.dumps({'interpreter':str(FRAMEWORK),'asan':str(asan),'leak_detection':False,'undefined_behavior_halts':True,'results':results},indent=2)+'\n')
sys.exit(0 if all(r['returncode']==0 for r in results) else 1)
