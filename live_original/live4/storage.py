"""Bound active evidence size without changing game actions or observations."""
import gzip
import hashlib
import json
import lzma
from pathlib import Path
import re
import sys

H = Path(__file__).resolve().parent.parent/'live3'
sys.path.insert(0, str(H))
from batch import compact as legacy_compact

def install(base):
    from sim_patch.parity import core
    original = core.write_json
    def write(path, value):
        path = Path(path)
        match = re.fullmatch(r'(step|decision|plan)-[0-9]+\.json(?:\.gz)?', path.name)
        if not match:
            return original(path, value)
        path.parent.mkdir(parents=True, exist_ok=True)
        journal = path.parent/(match[1]+'.journal.jsonl.xz')
        if journal not in core._JOURNALS:
            core._JOURNALS[journal] = lzma.open(journal, 'wt', preset=3)
        stream = core._JOURNALS[journal]
        stream.write(json.dumps(dict(file=path.name,data=value),ensure_ascii=False,
                               separators=(',',':'),allow_nan=False)+'\n')
        stream.flush()
    base.L.write_json = write
    base.write_json = write

def compact(out):
    # Existing gzip cohorts stay readable, and disposal remains task-scoped.
    legacy_compact(out)
    archive = json.loads((out/'archive.json').read_text())
    verified = {}
    for stem, name in [('step','steps'),('decision','decisions'),('plan','plans')]:
        journal = out/(stem+'.journal.jsonl.xz')
        if not journal.exists():
            continue
        target = out/(name+'.jsonl.xz')
        if target.exists():
            raise FileExistsError(target)
        count = 0
        last = None
        digest = hashlib.sha256()
        def emit(row, dst):
            raw = (json.dumps(row,separators=(',',':'))+'\n').encode()
            digest.update(raw)
            dst.write(raw)
        with lzma.open(journal,'rt') as src, lzma.open(target,'wb',preset=3) as dst:
            for line in src:
                row = json.loads(line)
                if last is not None and row['file'] != last['file']:
                    if row['file'] <= last['file']:
                        raise ValueError('journal file order regressed')
                    emit(last,dst);count += 1
                last = row
            if last is not None:
                emit(last,dst);count += 1
        check = hashlib.sha256()
        with lzma.open(target,'rb') as src:
            lines = 0
            for line in src:
                check.update(line);lines += 1
        if check.digest() != digest.digest() or lines != count:
            raise ValueError('xz evidence verification failed')
        verified[target.name] = dict(sha256=digest.hexdigest(),records=count)
        archive['counts'][name] = count
        journal.unlink()
    archive['xz_verified'] = verified
    (out/'archive.json').write_text(json.dumps(archive,indent=2))
