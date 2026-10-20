import copy,json,subprocess,sys,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[2];parent=Path(__file__).parent
sys.path[:0]=[str(parent),str(root/'tests')]
from hotplug_endpoint import validate_rows
from muted_endpoint import validate_report as strict_report

def device(i,v=.7,available=True):
    return dict(token=i,available=available,device_state=1 if available else 4,
        muted=True if available else None,volume=v if available else None,same_device_volume=True if available else None)
def sample(ms,selected,devices,changed=False):
    return dict(schema_version=1,event='sample',elapsed_ms=ms,default_token=selected,default_changed=changed,endpoints=devices)
good=[sample(0,0,[device(0)]),sample(25,1,[device(0),device(1,.4)],True),
      sample(50,1,[device(0,available=False),device(1,.4)]),
      sample(75,0,[device(0),device(1,.4)],True),
      dict(schema_version=1,event='summary',status='passed',samples=4,default_changes=2,endpoint_identities=2)]
assert validate_rows(good)['default_changes']==2
cases=[]
for k,v in [('muted',False),('volume',.8),('same_device_volume',False),('available',False),('token',True)]:
    bad=copy.deepcopy(good);bad[1]['endpoints'][0][k]=v;cases.append(bad)
for index,k,v in [(1,'volume',.6),(1,'muted',False),(1,'same_device_volume',False)]:
    bad=copy.deepcopy(good);bad[2]['endpoints'][index][k]=v;cases.append(bad)
bad=copy.deepcopy(good);bad[3]['endpoints'][0]['volume']=.8;cases.append(bad)
bad=copy.deepcopy(good);bad[2]['endpoints'].pop(0);cases.append(bad)
bad=copy.deepcopy(good);bad[1]['default_changed']=False;cases.append(bad)
bad=copy.deepcopy(good);bad[1]['default_token']=0;cases.append(bad)
bad=copy.deepcopy(good);bad[2]['endpoints'][0]['muted']=True;cases.append(bad)
bad=copy.deepcopy(good);bad[2]['endpoints'][1]=device(1,available=False);cases.append(bad)
bad=copy.deepcopy(good);bad[-1]['samples']=3;cases.append(bad)
bad=copy.deepcopy(good);bad[-1]['default_changes']=1;cases.append(bad)
bad=copy.deepcopy(good);bad[-1]['endpoint_identities']=3;cases.append(bad)
bad=copy.deepcopy(good);bad[2]['elapsed_ms']=1;cases.append(bad)
cases.extend([good[:-1],good[1:]])
for i,bad in enumerate(cases):
    try:validate_rows(bad)
    except (RuntimeError,KeyError):pass
    else:raise AssertionError(f'Negative case {i} accepted')
helper=parent/'endpoint-v3/hotplug-endpoint-observer.exe'
with tempfile.TemporaryDirectory() as tmp:
    t=Path(tmp)
    for value in ('0','nan','600001','-1'):
        p=subprocess.run([str(helper),'--watch',str(t/'a'),str(t/'b'),str(t/'c'),value],capture_output=True,timeout=5)
        assert p.returncode!=0 and not list(t.iterdir())
    strict=[dict(elapsed_ms=0,muted=True,volume=1,same_endpoint=True),
        dict(elapsed_ms=25,muted=True,volume=1,same_endpoint=False),dict(status='passed',samples=2)]
    p=t/'strict.jsonl';p.write_bytes(('\n'.join(map(json.dumps,strict))+'\n').encode())
    try:strict_report(p)
    except RuntimeError:pass
    else:raise AssertionError('Original strict contract was weakened')
print(json.dumps(dict(status='passed',positive_protocol_case=1,negative_evidence_cases=len(cases),
    native_argument_rejections=4,original_strict_change_rejection='preserved',physical_testing=False)))
