# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Human-only disconnected-close instructions. No input/window/device control."""
import json
import time
from dualsense_guide import Guide


class CloseGuide(Guide):
    def __init__(self, output, plan):
        self.index = None; self.mode = 'ready'; self.started_qpc = None
        self.action_confirmed = self.capture_confirmed = False
        self.unplug_instruction_qpc = self.close_instruction_qpc = self.closed_confirmed_qpc = None
        self.action_instruction_qpc = None; self.before_close = None; self.callback_error = None
        super().__init__(output, plan)
        import tkinter as tk
        self.root.geometry('490x560+10+10')
        self.confirm_button = tk.Button(self.root, command=self.confirm, wraplength=440)
        self.confirm_button.pack(padx=10, pady=8)
        self.root.report_callback_exception = self.callback_failed
        self.title.set('Disconnected-close test — waiting for Ready')
        self.text.set('Keep Windows muted. Leave USB connected and all controls untouched. '
                      'Three F12 captures, one separately confirmed unplug, then close the game. '
                      'Do NOT reconnect or press controller buttons.')
        self.confirm_button.configure(text='Waiting for test', state='disabled')

    def callback_failed(self, kind, error, traceback):
        self.callback_error = str(error)

    def pump(self):
        super().pump()
        if self.callback_error is not None:
            raise ValueError('Instruction callback failed: '+self.callback_error)

    def log(self, event, **fields):
        with (self.output/'human-confirmations.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, index=self.index,
                                        qpc_seconds=time.perf_counter(), **fields))+'\n')

    def ready(self):
        self.started_qpc = time.perf_counter()
        self.log('human_ready_clicked')
        super().ready()

    def stage(self, index):
        if type(index) is not int or index not in (0, 1, 2) or index != (0 if self.index is None else self.index+1) or (index and self.mode != 'waiting-image'):
            raise ValueError('Instruction stage skipped or repeated')
        self.index = index; self.action_confirmed = self.capture_confirmed = False
        self.mode = 'unplug-permission' if index == 1 else 'action'
        self.action_instruction_qpc = None if index == 1 else time.perf_counter()
        self.log('stage_prompt', mode=self.mode)
        self.render()

    def capture(self):
        if self.mode != 'waiting' or not self.action_confirmed:
            raise ValueError('Capture before human action confirmation')
        self.mode = 'capture'; self.log('capture_prompt'); self.render()

    def finish(self, before_close):
        if self.index != 2 or self.mode != 'waiting-image':
            raise ValueError('Close before three verified captures')
        self.before_close = before_close
        self.mode = 'close-permission'; self.log('close_readiness_prompt'); self.render()

    def confirm(self):
        old = self.mode
        if old == 'unplug-permission':
            self.unplug_instruction_qpc = self.action_instruction_qpc = time.perf_counter()
            self.mode = 'action'; self.log('usb_action_instruction')
        elif old == 'action':
            self.action_confirmed = True; self.mode = 'waiting'
        elif old == 'capture':
            self.capture_confirmed = True; self.mode = 'waiting-image'
        elif old == 'close-permission':
            self.before_close()  # Validate the still-owned live window before instructing X.
            self.close_instruction_qpc = time.perf_counter()
            self.mode = 'close'; self.log('normal_close_instruction')
        elif old == 'close':
            self.closed_confirmed_qpc = time.perf_counter(); self.mode = 'closed'
        else:
            raise ValueError('No pending human confirmation')
        self.log('human_confirmation', confirmed_step=old)
        self.render()

    def render(self):
        title, text, button = {
            'unplug-permission': ('CONFIRM READINESS FIRST', 'Do NOT unplug yet. Click below when ready for the explicit unplug instruction.', 'Ready to unplug once'),
            'action': (('INITIAL NEUTRAL', 'Leave all controls untouched. Click the new game window, then confirm here.', 'Neutral; game focused — confirm') if self.index == 0 else
                       ('UNPLUG USB ONCE NOW', 'Physically unplug USB once, then confirm here. Leave it disconnected. Do not reconnect or press PS.', 'USB unplugged once — confirm') if self.index == 1 else
                       ('STILL DISCONNECTED', 'Keep USB disconnected. Leave every control untouched, then confirm here.', 'Still disconnected — confirm')),
            'waiting': ('WAIT — NO PHYSICAL ACTION', 'Wait for sustained guest/SDL qualification and F12 NOW.', 'Waiting'),
            'capture': ('F12 NOW — ONE CAPTURE', 'Click the game and physically press F12 (Fn if needed), not F11. After its screenshot notification, confirm below. Keep the current USB state.', 'Screenshot notification appeared — confirm'),
            'waiting-image': ('WAIT — VERIFYING ORIGINAL IMAGE', 'Keep the current USB state. No extra captures or controls.', 'Waiting'),
            'close-permission': ('READY TO CLOSE — NOT YET', 'All three images passed. Leave USB DISCONNECTED. Confirm readiness; the next panel will instruct you to click the game X.', 'Ready to close the game'),
            'close': ('CLOSE GAME NORMALLY NOW', 'Leave USB DISCONNECTED. Click only the GAME window X. Do not close this panel. Then confirm below.', 'Game closed normally — confirm'),
            'closed': ('CLOSE CONFIRMATION RECORDED', 'Leave USB disconnected. Wait for process-tree and evidence verification.', 'Waiting'),
        }[self.mode]
        self.title.set(title)
        self.text.set(text+'\n\nKeep Windows MUTED. No reconnect, controller input or settings changes. '
                      'One attempt; six-minute total budget. Close within 30 seconds of CLOSE GAME NOW.')
        self.confirm_button.configure(text=button, state='normal' if self.mode in
                                      ('unplug-permission', 'action', 'capture', 'close-permission', 'close') else 'disabled')
        self.pump()
