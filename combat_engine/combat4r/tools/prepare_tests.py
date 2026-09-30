from pathlib import Path
r=Path(__file__).resolve().parents[1];s=r/'snapshots/parity-sim_patch';v=r/'validation';a=v/'alignment';a.mkdir(parents=True,exist_ok=True)
for dest,source in [(a/'tests',s/'alignment/tests'),(v/'tests',s/'tests')]:
 if not dest.exists():dest.symlink_to(source,target_is_directory=True)
t=(s/'alignment/CMakeLists.txt').read_text()
t=t.replace('add_library(sts_core STATIC ${CORE_SOURCES})','add_library(sts_core STATIC IMPORTED GLOBAL)\nset_target_properties(sts_core PROPERTIES IMPORTED_LOCATION "${CORE_ARCHIVE}")')
t=t.replace('target_include_directories(sts_core PUBLIC','target_include_directories(sts_core INTERFACE')
t=t.replace('target_compile_options(sts_core PRIVATE -O2 -UNDEBUG)','target_compile_definitions(sts_core INTERFACE COMBAT3_TARGET_POLICY=1)')
# Test binaries and original-capture checks share the delivered core archive.
(a/'CMakeLists.txt').write_text(t)
