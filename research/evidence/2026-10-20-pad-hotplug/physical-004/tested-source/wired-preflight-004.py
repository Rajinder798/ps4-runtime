import json,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'tests'))
from muted_endpoint import MutedEndpoint,validate_report
out=root/'build/dualsense-hotplug-physical/preflight-004/wired'
out.mkdir(exist_ok=False)
probe=root/'build/dualsense-hotplug-implementation/probe-001/dualsense-sdl-probe.exe'
with MutedEndpoint(root/'build/native/ps4-endpoint-observer.exe',out) as endpoint:
    with (out/'sdl-stdout.json').open('wb') as so,(out/'sdl-stderr.txt').open('wb') as se:
        child=subprocess.Popen([str(probe),'--watch',str(out/'native.jsonl'),str(out/'stop.request'),str(out/'ready.txt'),'5000'],stdout=so,stderr=se)
        try:
            deadline=time.monotonic()+4
            while not (out/'ready.txt').exists():
                endpoint.check()
                if child.poll() is not None or time.monotonic()>deadline:raise RuntimeError('Wired discovery did not become ready')
                time.sleep(.025)
            time.sleep(.2);endpoint.check()
        finally:
            (out/'stop.request').touch(exist_ok=True)
            try:child.wait(timeout=2)
            except subprocess.TimeoutExpired:child.kill();child.wait();raise RuntimeError('Discovery cleanup needed termination')
        assert child.returncode==0,(out/'sdl-stderr.txt').read_text()
rows=[json.loads(s) for s in (out/'native.jsonl').read_text().splitlines()]
assert rows[0]['connection']=='wired' and rows[0]['virtual'] is False
assert all(r.get('buttons',0)==0 for r in rows),'Controller not neutral'
result=dict(wired=True,neutral=True,endpoint=validate_report(out/'endpoint.jsonl'),actual_guest_started=False)
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
