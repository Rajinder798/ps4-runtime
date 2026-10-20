"""Use REAL generated instructions through the REAL guide methods; no Tk/device."""
from pathlib import Path
import hashlib,json,sys,tempfile
root=Path(__file__).resolve().parents[2]
parent=Path(__file__).parent
sys.path[:0]=[str(parent/'confirmation-v4'),str(root/'tests'),str(root/'tools')]
from confirmed_guide import ConfirmedGuide
import confirmed_runner as runner

class Value:
    def set(self,value):self.value=value
class Button:
    def configure(self,**values):self.values=values

with tempfile.TemporaryDirectory() as tmp:
    g=ConfirmedGuide.__new__(ConfirmedGuide)
    from confirmed_guide import ConfirmationState
    g.confirmations=ConfirmationState();g.output=Path(tmp)
    g.title=Value();g.text=Value();g.confirm_button=Button();g.pump=lambda:None
    checks=0
    for index in range(7):
        title,text=runner.instruction(index)
        assert '\u2014' in title and '\u20ac' not in title
        # Regression: pass the actual generated title to the real UI parser.
        g.show(title,text)
        assert g.confirmations.index==index and g.confirm_button.values['state']=='normal'
        assert not g.action_confirmed and not g.capture_confirmed;checks+=3
        if index in (2,4):
            assert g.confirmations.mode=='permission'
            assert 'Do NOT do it yet' in g.text.value
            g.confirm();assert g.confirmations.mode=='action' and not g.action_confirmed;checks+=3
        g.confirm()
        if index==2:
            assert not g.action_confirmed and g.confirmations.mode=='release-disconnected'
            g.confirm();checks+=1
        assert g.action_confirmed and not g.capture_confirmed;checks+=1
        title,text=runner.instruction(index,True)
        g.show(title,text)
        assert g.confirmations.mode=='capture' and g.confirm_button.values['state']=='normal';checks+=1
        g.confirm();assert g.capture_confirmed and g.confirm_button.values['state']=='disabled';checks+=1
    g.finish();assert g.confirmations.mode=='close'
    g.confirm();assert g.confirmations.closed_confirmed;checks+=2
    rows=[json.loads(s) for s in (g.output/'human-confirmations.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len([r for r in rows if r['event']=='stage_prompt'])==7
    assert len([r for r in rows if r['event']=='capture_prompt'])==7
    assert len([r for r in rows if r['event']=='human_confirmation'])==18
    assert len([r for r in rows if r['event']=='usb_action_instruction'])==2;checks+=4
    # Deliberately corrupted v1 labels reproduce the parser failure, not a pass.
    bad=runner.instruction(0)[0].encode('utf-8').decode('cp1252')
    assert __import__('re').match(r'(\d)/7 — (.*)',bad) is None;checks+=1
    source=(parent/'confirmation-v4/confirmed_runner.py').read_text(encoding='utf-8')
    assert 'Screenshot before phase qualification' in source
    assert 'Approved 360-second human test budget exceeded' in source
    assert 'guide.action_confirmed and not capture_announced' in source
    assert 'if not guide.capture_confirmed: continue' in source;checks+=4
from confirmed_guide import reconnect_expired
assert not reconnect_expired(None,1000)
assert not reconnect_expired(100,129.999)
assert not reconnect_expired(100,130)
assert reconnect_expired(100,130.001)
assert g.unplug_instruction_monotonic is not None and g.reconnect_instruction_monotonic is not None
assert 'reconnect_expired(guide.reconnect_instruction_monotonic,time.monotonic())' in source
checks+=6
report=dict(status='passed',checks=checks,actual_instruction_labels=14,
    physical_session_started=False,tk_or_device_initialized=False,
    scope='Real v4 instruction generation, guide parsing/rendering/confirm callbacks, USB authorization/release/close gates; v1 corruption rejected',
    source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(__file__),parent/'prepare-v4.py',parent/'confirmation-v4/confirmed_runner.py',parent/'confirmation-v4/confirmed_guide.py']})
(parent/'confirmation-v4/host-test.json').write_bytes((json.dumps(report,indent=2)+'\n').encode('utf-8'))
print(json.dumps(report))
