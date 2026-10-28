# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Human-action protocol for later separately authorized v2 hardware verification.

This module never launches a process, injects input, closes windows or controls USB.
The physical collector is deliberately not an automated guest-regression mode.
"""
import json
import time

RECOVERY = ('initial-neutral','cross','release','held-before-unplug','disconnected',
            'disconnected-progress','reconnected-neutral','reconnected-cross','reconnected-release')
DISCONNECTED_CLOSE = ('initial-neutral','disconnected','disconnected-progress')
ACTIONS = {
    'initial-neutral': 'Keep USB connected; leave all controls untouched.',
    'cross': 'Physically press and hold Cross.',
    'release': 'Release Cross; leave all controls untouched.',
    'held-before-unplug': 'Physically hold Cross until unplug is instructed.',
    'disconnected': 'Unplug USB exactly once NOW. Then release Cross on the disconnected controller.',
    'disconnected-progress': 'Keep USB disconnected and controls untouched.',
    'reconnected-neutral': 'Reconnect the SAME controller by USB-C exactly once NOW; leave controls untouched.',
    'reconnected-cross': 'Physically press and hold Cross after recovery.',
    'reconnected-release': 'Release Cross; leave all controls untouched.',
}


class Protocol:
    """Collector must qualify real SDL/Pad/image evidence before advance()."""
    def __init__(self, scenario, *, physical_authorized=False, disconnect_authorized=False, reconnect_authorized=False, before_close=None):
        if scenario not in ('recovery','disconnected-close'):
            raise ValueError('Unknown physical plan')
        if not physical_authorized or not disconnect_authorized or (scenario=='recovery') != bool(reconnect_authorized):
            raise ValueError('Separate scenario/USB permissions required')
        self.plan=RECOVERY if scenario=='recovery' else DISCONNECTED_CLOSE
        self.index=-1;self.mode='ready';self.events=[];self.started=None
        self.before_close=before_close
    def log(self,event):
        self.events.append(dict(event=event,index=self.index,qpc_seconds=time.perf_counter()))
    def ready(self):
        if self.mode!='ready':raise ValueError('Ready repeated')
        self.started=time.perf_counter();self.log('human_ready_clicked');self.advance()
    def advance(self):
        if self.mode not in ('ready','verified'):raise ValueError('Missing verified original image')
        self.index+=1
        if self.index==len(self.plan):self.mode='close-permission'
        else:self.mode='usb-permission' if self.plan[self.index] in ('disconnected','reconnected-neutral') else 'action'
        self.log(self.mode)
    def confirm(self):
        if self.mode=='usb-permission':self.mode='action';self.log('usb_action_instruction')
        elif self.mode=='action':self.mode='qualifying';self.log('human_action_confirmed')
        elif self.mode=='capture':self.mode='waiting-image';self.log('human_f12_confirmed')
        elif self.mode=='close-permission':
            if self.before_close is None:raise ValueError('Owned live-window verification required before instructing close')
            self.before_close()
            self.mode='close';self.log('normal_close_instruction')
        elif self.mode=='close':self.mode='closed';self.log('human_close_confirmed')
        else:raise ValueError('No pending physical confirmation')
    def capture(self):
        if self.mode!='qualifying':raise ValueError('Capture before action/state qualification')
        self.mode='capture';self.log('capture_prompt')
    def verified(self):
        if self.mode!='waiting-image':raise ValueError('No original image awaiting verification')
        self.mode='verified';self.advance()
    def check_budget(self, now=None):
        if self.started is not None and (time.perf_counter() if now is None else now)-self.started>360:
            raise ValueError('Six-minute physical attempt expired; no retry')
    def instruction(self):
        if self.mode=='ready':return 'Wait for separately approved hardware session. No action yet.'
        if self.mode=='usb-permission':return 'Do NOT change USB yet. Confirm readiness for the next explicit USB instruction.'
        if self.mode=='action':return ACTIONS[self.plan[self.index]]+' Confirm after that action.'
        if self.mode=='capture':return 'F12 NOW: capture once, preserving current USB/control state. Confirm its notification.'
        if self.mode=='close-permission':return 'All original images verified. Do NOT close yet; confirm readiness.'
        if self.mode=='close':return 'Click only the game window X now. Preserve current USB state; confirm after closing.'
        return 'Wait. Preserve current USB/control state; no extra physical actions.'


class Guide:
    """Optional panel. Caller owns evidence qualification, permissions and cleanup."""
    def __init__(self, protocol, output):
        import tkinter as tk
        self.protocol,self.output=protocol,output
        self.root=tk.Tk();self.root.title('Live AV v2 physical instructions');self.root.geometry('490x430+10+10')
        self.text=tk.StringVar();tk.Label(self.root,textvariable=self.text,wraplength=455,justify='left').pack(padx=15,pady=20)
        self.button=tk.Button(self.root,text='Confirm',command=self.confirm);self.button.pack(pady=15)
        self.callback_error=None;self.root.report_callback_exception=lambda kind,error,tb:setattr(self,'callback_error',str(error))
        self.render()
    def confirm(self):
        if self.protocol.mode=='ready':self.protocol.ready()
        else:self.protocol.confirm()
        self.render()
    def render(self):
        self.text.set(self.protocol.instruction()+'\n\nKeep Windows muted. No settings changes or extra USB actions.')
        self.button.configure(state='normal' if self.protocol.mode in ('ready','usb-permission','action','capture','close-permission','close') else 'disabled')
        self.output.write_text(''.join(json.dumps(e)+'\n' for e in self.protocol.events),encoding='utf-8')
    def pump(self):
        self.root.update_idletasks();self.root.update();self.protocol.check_budget()
        if self.callback_error:raise ValueError('Guide callback failed: '+self.callback_error)
    def close(self):self.root.destroy()
