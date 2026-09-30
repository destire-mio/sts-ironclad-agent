"""Lossless packing of finished evidence to fit the available local disk."""
import argparse,gzip,hashlib,json,lzma,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def pack(directory):
    if not (directory/'archive.json').exists() or (directory/'packed.json').exists():return
    records={}
    for p in [*directory.glob('*.jsonl.gz'),*directory.joinpath('original').glob('*.json.gz'),
              *directory.joinpath('original').glob('*.jsonl.gz')]:
        target=p.with_suffix('.xz');temporary=target.with_suffix('.packing');digest=hashlib.sha256();size=0
        with gzip.open(p,'rb') as src,lzma.open(temporary,'wb',preset=3) as dst:
            while chunk:=src.read(1024*1024):digest.update(chunk);size+=len(chunk);dst.write(chunk)
        check=hashlib.sha256()
        with lzma.open(temporary,'rb') as src:
            while chunk:=src.read(1024*1024):check.update(chunk)
        assert check.digest()==digest.digest()
        temporary.replace(target);p.unlink()
        records[str(target.relative_to(directory))]=dict(uncompressed_bytes=size,sha256=digest.hexdigest())
    (directory/'packed.json').write_text(json.dumps(records,indent=2))
    print(json.dumps(dict(packed=str(directory))),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args()
    while True:
        for parent in ('pilot','cohort'):
            for f in (HERE/parent).glob('*/archive.json'):pack(f.parent)
        if not a.watch:break
        state=HERE/'cohort/progress.json'
        try:
            d=json.loads(state.read_text())
            if not d['pending'] and not d['active']:break
        except (FileNotFoundError,json.JSONDecodeError):pass
        time.sleep(5)

if __name__=='__main__':main()
