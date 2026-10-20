from pathlib import Path
import difflib,hashlib,json
root=Path(__file__).resolve().parents[2];parent=Path(__file__).parent
out=parent/'confirmation-v4';out.mkdir(exist_ok=False)
guide=(parent/'confirmation-v3/confirmed_guide.py').read_text(encoding='utf-8')
guide=guide.replace('class ConfirmedGuide(Guide):',
    'def reconnect_expired(instruction_started, now):\n    return instruction_started is not None and now-instruction_started>30\n\n\nclass ConfirmedGuide(Guide):')
guide=guide.replace('self.confirmations=ConfirmationState();self.start_qpc=None',
    'self.confirmations=ConfirmationState();self.start_qpc=None\n        self.reconnect_instruction_monotonic=None\n        self.unplug_instruction_monotonic=None')
old="        if old=='permission':self.log('usb_action_instruction')"
assert guide.count(old)==1
guide=guide.replace(old,"        if old=='permission':\n            if self.confirmations.index==4:self.reconnect_instruction_monotonic=time.monotonic()\n            if self.confirmations.index==2:self.unplug_instruction_monotonic=time.monotonic()\n            self.log('usb_action_instruction')")
source=(parent/'confirmation-v3/confirmed_runner.py').read_text(encoding='utf-8')
source=source.replace('from confirmed_guide import ConfirmedGuide as Guide','from confirmed_guide import ConfirmedGuide as Guide,reconnect_expired')
old="                if not reconnected and time.monotonic()-phase['issued_monotonic']>30:"
assert source.count(old)==1
source=source.replace(old,'                if not reconnected and reconnect_expired(guide.reconnect_instruction_monotonic,time.monotonic()):')
old="            if removed and phase['index']<2:"
assert source.count(old)==1
source=source.replace(old,"            if removed and guide.unplug_instruction_monotonic is None: raise ValueError('USB removed before separately confirmed instruction')\n            if len(opened)>1 and guide.reconnect_instruction_monotonic is None: raise ValueError('USB reconnected before separately confirmed instruction')\n"+old)
for name,contents in [('confirmed_runner.py',source),('confirmed_guide.py',guide),
        ('hotplug_endpoint.py',(parent/'confirmation-v3/hotplug_endpoint.py').read_text(encoding='utf-8'))]:
    (out/name).write_bytes(contents.encode('utf-8'))
original=(root/'tests/pad_hotplug_guest_tests.py').read_text(encoding='utf-8')
(out/'changes-from-approved-runner.diff').write_bytes(''.join(difflib.unified_diff(original.splitlines(True),source.splitlines(True),fromfile='e940d20/tests/pad_hotplug_guest_tests.py',tofile='confirmation-v4/confirmed_runner.py')).encode('utf-8'))
context=json.loads((parent/'confirmation-v3/runner-context.json').read_text(encoding='utf-8'))
context.update(authorization='Owner requested check the termination and restart the session',
    reconnect_timer_fix='Unchanged 30-second reconnect deadline begins only after human readiness confirmation and explicit RECONNECT NOW instruction, not while reading the permission prompt',
    unexpected_usb_actions_rejected=True,
    source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [out/'confirmed_runner.py',out/'confirmed_guide.py',out/'hotplug_endpoint.py',parent/'hotplug_endpoint_observer.cpp']})
(out/'runner-context.json').write_bytes((json.dumps(context,indent=2)+'\n').encode('utf-8'))
tests=(parent/'confirmation-v3-tests.py').read_text(encoding='utf-8').replace('confirmation-v3','confirmation-v4').replace('prepare-v3.py','prepare-v4.py').replace('Real v3 instruction','Real v4 instruction')
# This tests the actual GUI callbacks and exact function used by the live loop.
tests=tests.replace("report=dict(status='passed'", "from confirmed_guide import reconnect_expired\nassert not reconnect_expired(None,1000)\nassert not reconnect_expired(100,129.999)\nassert not reconnect_expired(100,130)\nassert reconnect_expired(100,130.001)\nassert g.unplug_instruction_monotonic is not None and g.reconnect_instruction_monotonic is not None\nassert 'reconnect_expired(guide.reconnect_instruction_monotonic,time.monotonic())' in source\nchecks+=6\nreport=dict(status='passed'")
(parent/'confirmation-v4-tests.py').write_bytes(tests.encode('utf-8'))
preflight=(parent/'preflight-v3.py').read_text(encoding='utf-8').replace('confirmation-v3','confirmation-v4').replace('preflight-003','preflight-004')
(parent/'preflight-v4.py').write_bytes(preflight.encode('utf-8'))
wired=(parent/'wired-preflight.py').read_text(encoding='utf-8').replace('preflight-001','preflight-004')
(parent/'wired-preflight-004.py').write_bytes(wired.encode('utf-8'))
print('v4 timer fix and explicit USB permission gates prepared; no guest/session started')
