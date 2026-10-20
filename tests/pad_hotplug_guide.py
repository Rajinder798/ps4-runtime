# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Session-only human confirmation UI; no input/device/audio/window-control APIs."""
import json
import re
import time
from dualsense_guide import Guide


class ConfirmationState:
    def __init__(self):
        self.index=None;self.mode=None
        self.action_confirmed=False;self.capture_confirmed=False;self.closed_confirmed=False
    def begin(self,index,capture=False):
        if index!=self.index:
            self.index=index;self.action_confirmed=self.capture_confirmed=False
            self.mode='permission' if index in (2,4) else 'action'
        if capture:
            if not self.action_confirmed: raise ValueError('Capture before action confirmation')
            self.mode='capture'
    def confirm(self):
        old=self.mode
        if old=='permission':self.mode='action'
        elif old=='action' and self.index==2:self.mode='release-disconnected'
        elif old in ('action','release-disconnected'):
            self.action_confirmed=True;self.mode='waiting'
        elif old=='capture':self.capture_confirmed=True;self.mode='waiting-image'
        elif old=='close':self.closed_confirmed=True;self.mode='closed'
        else:raise ValueError('No pending confirmation')
        return old


def reconnect_expired(instruction_started, now):
    return instruction_started is not None and now-instruction_started>30


class ConfirmedGuide(Guide):
    def __init__(self,output,plan):
        self.confirmations=ConfirmationState();self.start_qpc=None
        self.reconnect_instruction_monotonic=None
        self.unplug_instruction_monotonic=None
        super().__init__(output,plan)
        import tkinter as tk
        self.root.geometry('490x580+10+10')
        self.confirm_button=tk.Button(self.root,text='Waiting',command=self.confirm,state='disabled',wraplength=440)
        self.confirm_button.pack(padx=10,pady=8)
    @property
    def action_confirmed(self):return self.confirmations.action_confirmed
    @property
    def capture_confirmed(self):return self.confirmations.capture_confirmed
    def log(self,event,**fields):
        with (self.output/'human-confirmations.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(event=event,index=self.confirmations.index,
                qpc_seconds=time.perf_counter(),monotonic=time.monotonic(),**fields))+'\n')
    def ready(self):
        self.start_qpc=time.perf_counter()
        self.log('human_ready_clicked')
        super().ready()
    def show(self,title,text):
        match=re.match(r'(\d)/7 — (.*)',title)
        if match:
            index=int(match[1])-1;capture=match[2].startswith('F12 NOW')
            self.confirmations.begin(index,capture)
            self.log('capture_prompt' if capture else 'stage_prompt',title=title)
            self.render()
        else:
            super().show(title,text)
    def render(self):
        c=self.confirmations;i=c.index;mode=c.mode
        prefix=f'{i+1}/7 — ' if i is not None else ''
        if mode=='permission':
            verb='unplug' if i==2 else 'reconnect'
            title='CONFIRM INSTRUCTION FIRST'
            text=('Keep Cross HELD while confirming this panel. Use your other hand for the mouse.\n\n' if i==2 else '')+f'The next action will be to {verb} USB exactly ONCE. Do NOT do it yet.\n\nClick below only when ready. The next panel will explicitly tell you to act.'
            button=f'I understand — ready to {verb} USB once'
        elif mode=='release-disconnected':
            title='RELEASE CROSS — USB STAYS DISCONNECTED'
            text='You confirmed unplugging. Now release Cross on the disconnected controller. Leave USB disconnected, then confirm below.'
            button='Cross released while disconnected — confirm'
        elif mode=='action':
            title,text,button=(
                ('INITIAL NEUTRAL','Click the NEW game window. Leave all controls untouched, then confirm here.','Game focused; controller neutral — confirm'),
                ('HOLD CROSS','Press and KEEP HOLDING only Cross, then confirm here. Do not release until the later release instruction.','Holding Cross — confirm'),
                ('UNPLUG USB ONCE NOW','Physically unplug the USB cable ONCE. Keep Cross held until the next instruction. Leave USB disconnected, then confirm here.','USB unplugged once — confirm'),
                ('LEAVE USB DISCONNECTED','Keep USB disconnected, controls released. Confirm that state, then wait for the progress capture.','Still disconnected; controls released — confirm'),
                ('RECONNECT SAME USB ONCE NOW','Reconnect the SAME controller by USB-C ONCE, all controls untouched. Do not press PS. Then confirm here.','USB reconnected once; controls neutral — confirm'),
                ('HOLD CROSS AFTER RECOVERY','Press and KEEP HOLDING only Cross on the reconnected controller, then confirm here.','Holding Cross after recovery — confirm'),
                ('RELEASE CROSS','Release Cross completely. Leave every control untouched, then confirm here.','Cross released; controller neutral — confirm')
            )[i]
        elif mode=='capture':
            title='F12 NOW — ONE SCREENSHOT'
            text='Click inside the game window. Keep the current USB/control state. Physically press F12 (Fn+F12 if needed), NOT F11.\n\nAfter the screenshot notification, confirm below. Keep Cross held during either HOLD stage.'
            button='Screenshot notification appeared — confirm F12'
        elif mode=='close':
            title='CLOSE GAME NORMALLY'
            text='All seven images were verified. Controller neutral; USB stays connected. Close only the GAME window using its X. Then confirm here. Do not close this panel.'
            button='Game closed normally — confirm'
        else:
            title='WAIT — NO NEW PHYSICAL ACTION'
            text='Your confirmation was recorded. Keep the current USB/control state. Wait for the next instruction. Keep Cross held if this is a HOLD stage.'
            button='Confirmation recorded — waiting'
        self.title.set(prefix+title)
        self.text.set(text+'\n\nKeep Windows MUTED. No extra key/button presses or USB actions. One attempt; six-minute session budget.')
        self.confirm_button.configure(text=button,state='normal' if mode in ('permission','action','release-disconnected','capture','close') else 'disabled')
        self.pump()
    def confirm(self):
        old=self.confirmations.confirm()
        self.log('human_confirmation',confirmed_step=old)
        if old=='permission':
            if self.confirmations.index==4:self.reconnect_instruction_monotonic=time.monotonic()
            if self.confirmations.index==2:self.unplug_instruction_monotonic=time.monotonic()
            self.log('usb_action_instruction')
        self.render()
    def finish(self):
        self.confirmations.mode='close';self.log('normal_close_instruction');self.render()
    def wait_close_confirmation(self,endpoint):
        while not self.confirmations.closed_confirmed:
            self.pump();endpoint.check()
            if time.perf_counter()-self.start_qpc>360:raise ValueError('Close confirmation exceeded original 360-second session budget')
            time.sleep(.025)
