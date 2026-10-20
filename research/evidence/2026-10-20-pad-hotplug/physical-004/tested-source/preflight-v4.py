import hashlib,json,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2];parent=Path(__file__).parent
sys.path[:0]=[str(parent/'confirmation-v4'),str(root/'tests'),str(root/'tools')]
from hotplug_endpoint import MutedEndpoint,validate_report
import run_homebrew_startup as startup
out=parent/'preflight-004';out.mkdir(exist_ok=False)
old=json.loads((parent/'preflight-002/result.json').read_text(encoding='utf-8'))
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()==old['commit']
assert not subprocess.check_output(['git','status','--porcelain'],cwd=root)
for key,record in old['inputs'].items():
    assert hashlib.sha256((root/record['path']).read_bytes()).hexdigest()==record['sha256'],key
startup.verify_inputs(root/old['inputs']['engine']['path'],root/old['inputs']['engine_report']['path'],root/old['inputs']['fixture']['path'],'pad-hotplug-av')
context=json.loads((parent/'confirmation-v4/runner-context.json').read_text(encoding='utf-8'))
helper=parent/'endpoint-v3/hotplug-endpoint-observer.exe'
assert hashlib.sha256(helper.read_bytes()).hexdigest()==context['endpoint_helper_sha256']
for key,digest in context['source_sha256'].items():
    p=parent/'confirmation-v4'/key if (parent/'confirmation-v4'/key).exists() else parent/key
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,key
with MutedEndpoint(helper,out) as endpoint:
    time.sleep(.2);endpoint.check()
report=dict(commit=old['commit'],pins_and_original_tools_revalidated=True,inputs=old['inputs'],
    endpoint=validate_report(out/'endpoint.jsonl'),new_protocol=context,guest_session_started=False)
(out/'result.json').write_bytes((json.dumps(report,indent=2)+'\n').encode('utf-8'))
print(json.dumps(dict(status='passed',endpoint=report['endpoint'],commit=report['commit'])))
