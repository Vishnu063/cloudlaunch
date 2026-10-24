"""Build/run an owned disposable CloudLaunch sample. Never touches pharmacy services."""
import argparse
import json
from pathlib import Path
import re
import secrets
import subprocess

LABEL='io.cloudlaunch.ecosystem-demo'


def docker(*args):
    return subprocess.check_output(['docker','--host=unix:///var/run/docker.sock',*args],timeout=120,text=True).strip()


def deploy(root):
    root=Path(root).resolve();release=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True,timeout=5).strip()
    if not re.fullmatch(r'[a-f0-9]{40,64}',release):raise ValueError('Immutable release ID required')
    token=secrets.token_hex(10);tag='cloudlaunch-ecosystem-demo:'+release
    docker('build','-t',tag,'-f',str(root/'demo/Dockerfile'),str(root))
    image=docker('image','inspect','--format','{{.Id}}',tag)
    cid=docker('run','-d','--label',LABEL+'='+token,'--name','cleco-'+token,'--memory','64m','--cpus','0.25',
      '--pids-limit','32','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
      '-p','127.0.0.1::8080',image)
    try:
        mapping=docker('port',cid,'8080/tcp')
        if not re.fullmatch(r'127\.0\.0\.1:[0-9]+',mapping):raise ValueError('Unexpected port mapping')
        return dict(container=cid,token=token,image_id=image,release_id=release,url='http://'+mapping+'/',service='ecosystem-demo')
    except BaseException:
        cleanup({'container':cid,'token':token});raise


def cleanup(state):
    raw=json.loads(docker('inspect',state['container']))[0]
    if raw['Config'].get('Labels',{}).get(LABEL)!=state['token']:raise ValueError('Ownership mismatch; cleanup refused')
    docker('rm','-f',state['container'])

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--allow-disposable-host',action='store_true');args=p.parse_args()
    if not args.allow_disposable_host:p.error('Explicit disposable-host opt-in required')
    print(json.dumps(deploy(args.root)))
