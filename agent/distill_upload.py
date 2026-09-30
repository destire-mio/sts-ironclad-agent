"""Resume an owned partial checkpoint via bounded SSH chunks; verify exact bytes.

Run only when cloud evaluation workers have exited. Uses at most --workers
remote cat processes, and never replaces the destination before SHA verification.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import shlex
import subprocess


def main():
    p=argparse.ArgumentParser(); p.add_argument('source'); p.add_argument('destination')
    p.add_argument('--host',default='sts'); p.add_argument('--ssh-config',required=True)
    p.add_argument('--workers',type=int,default=4); a=p.parse_args()
    assert 1 <= a.workers <= 7
    source=Path(a.source).read_bytes(); q=shlex.quote
    ssh=['ssh','-o','IPQoS=none','-F',a.ssh_config,a.host]
    def remote(command, data=None):
        return subprocess.run(ssh+[command],input=data,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,check=True).stdout.decode()
    destination=a.destination; folder=destination+'.upload'
    remote('mkdir -p '+q(folder))
    # The caller must stop any previous upload first. Preserve its completed prefix.
    remote('if test -f '+q(destination)+' && ! test -f '+q(folder+'/prefix')+
           '; then mv '+q(destination)+' '+q(folder+'/prefix')+'; fi')
    details=remote('if test -f '+q(folder+'/prefix')+'; then wc -c < '+q(folder+'/prefix')+
                   '; sha256sum '+q(folder+'/prefix')+'; else echo 0; fi').splitlines()
    offset=int(details[0])
    if offset:
        assert hashlib.sha256(source[:offset]).hexdigest()==details[1].split()[0], 'partial prefix differs'
    chunks=[(i,source[start:start+1048576]) for i,start in enumerate(range(offset,len(source),1048576))]
    def send(job):
        i,data=job; path=folder+f'/chunk-{i:04d}'
        remote('exec cat > '+q(path),data)
        return dict(chunk=i,bytes=len(data))
    with ThreadPoolExecutor(a.workers) as pool:
        for f in as_completed([pool.submit(send,j) for j in chunks]):
            print(json.dumps(f.result()),flush=True)
    parts=([folder+'/prefix'] if offset else [])+[folder+f'/chunk-{i:04d}' for i,_ in chunks]
    restored=folder+'/complete'
    remote('cat '+' '.join(map(q,parts))+' > '+q(restored))
    expected=hashlib.sha256(source).hexdigest()
    actual=remote('sha256sum '+q(restored)).split()[0]
    assert expected==actual,'assembled checkpoint differs'
    remote('mv '+q(restored)+' '+q(destination))
    print(json.dumps(dict(path=destination,sha256=actual,resumed_bytes=offset)),flush=True)


if __name__=='__main__':
    main()
