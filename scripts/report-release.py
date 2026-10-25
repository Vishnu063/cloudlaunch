"""Optional CloudLaunch deployment reporting; never deploys or rolls anything back."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time

STATUSES=('started','healthy','failed','rollback_started','rollback_verified','rollback_failed','security_failed')


def release_id():
    value=subprocess.check_output(['git','rev-parse','HEAD'],text=True,timeout=5).strip()
    if not re.fullmatch(r'[a-f0-9]{40,64}',value):raise ValueError('Immutable Git release ID unavailable')
    return value


def report(status, directory, image_id=None, health=None):
    if status not in STATUSES:raise ValueError('Unknown release outcome')
    root=Path(directory);root.mkdir(parents=True,exist_ok=True,mode=0o700);root.chmod(0o700)
    release=release_id();record=dict(release_id=release,status=status,image_id=image_id,health=health,time=datetime.now(timezone.utc).isoformat())
    path=root/'deployments.jsonl';fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    with os.fdopen(fd,'a') as stream:stream.write(json.dumps(record)+'\n')
    # node-exporter's textfile collector can read these constant-cardinality metrics.
    flags={name:1 if name==status else 0 for name in STATUSES}
    metrics=''.join(f'cloudlaunch_deployment_status{{status="{name}"}} {value}\n' for name,value in flags.items())
    metrics+='cloudlaunch_deployment_timestamp_seconds '+str(time.time())+'\n'
    rows=[json.loads(line) for line in path.read_text().splitlines()[-100:]]
    starts=[r for r in rows if r['release_id']==release and r['status']=='started']
    if starts:
        elapsed=(datetime.now(timezone.utc)-datetime.fromisoformat(starts[-1]['time'])).total_seconds()
        metrics+='cloudlaunch_deployment_duration_seconds '+str(round(elapsed,3))+'\n'
    temporary=root/'release.prom.tmp';temporary.write_text(metrics);temporary.chmod(0o600);os.replace(temporary,root/'release.prom')
    url=os.environ.get('OPS_PILOT_EVENT_URL')
    if not url:return {'reported_locally':True,'delivered':False,'reason':'optional integration disabled'}
    from triage.ecosystem import envelope,emit
    event=envelope('DeploymentEvent','cloudlaunch',os.environ.get('OPS_PILOT_SERVICE','cloudlaunch'),record,
                   correlation_id='release-'+release+'-'+os.environ.get('BUILD_NUMBER','local'))
    emit(event,url,os.environ.get('OPS_PILOT_EVENT_TOKEN',''),root/'outbox')
    return {'reported_locally':True,'delivered':True}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('status',choices=STATUSES);p.add_argument('--state-dir',type=Path,default=Path('.ecosystem-state'))
    args=p.parse_args()
    try:
        image=None
        if args.status in ('healthy','rollback_verified'):
            image=subprocess.check_output(['docker','inspect','--format','{{.Image}}','pharmacy-app'],text=True,timeout=5).strip()
        print(json.dumps(report(args.status,args.state_dir,image_id=image,health='verified by pipeline' if image else None)))
    except (OSError,ValueError,ImportError,subprocess.SubprocessError):p.exit(2,'Optional release reporting failed; inspect the private local audit/outbox. Deployment itself was not changed.\n')
if __name__=='__main__':main()
