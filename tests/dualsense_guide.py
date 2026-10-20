# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Human instructions for the opt-in hardware test, never a product frontend.

Updates existing labels without requesting foreground/focus. No input injection,
device control or audio APIs. The human starts and operates the entire test.
"""
import json
import time


class Guide:
    def __init__(self, output, plan, disconnect=False):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.title('DualSense physical test — instructions')
        self.root.geometry('420x420+15+15')
        self.root.attributes('-topmost', True)
        self.started = self.cancelled = False
        self.output, self.plan = output, plan
        self.disconnect_mode = disconnect
        self.title = tk.StringVar(value='Start with controller UNTOUCHED')
        self.text = tk.StringVar(value='Keep Windows muted. Connect USB and leave the controller neutral.\n\n'
            'After Ready, follow this panel while the game window stays focused. '
            'You will press the controller and F12 yourself.\n\nNo disconnect or reconnect in this test.')
        if disconnect:
            self.title.set('Approved USB disconnect test')
            self.text.set('Keep Windows muted. Leave USB connected and every controller control neutral.\n\n'
                'After Ready, capture neutral with F12. Unplug USB ONLY when this panel says UNPLUG USB NOW.\n\nDo not reconnect.')
        tk.Label(self.root,textvariable=self.title,font=('Segoe UI',14,'bold'),wraplength=375).pack(padx=12,pady=12)
        tk.Label(self.root,textvariable=self.text,font=('Segoe UI',11),justify='left',wraplength=375).pack(padx=12,pady=6)
        self.start = tk.Button(self.root,text='Ready — begin',command=self.ready)
        self.start.pack(pady=8)
        tk.Button(self.root,text='Stop test',command=self.cancel).pack(pady=4)
        self.root.protocol('WM_DELETE_WINDOW',self.cancel)

    def ready(self):
        self.started = True
        self.start.configure(state='disabled')
        (self.output/'human-ready-click.json').write_bytes((json.dumps(dict(
            source='human clicked Ready in local test panel',monotonic=time.monotonic()))+'\n').encode())
        self.show('Starting the guest','Leave all controller controls neutral.\n\nWait for the next instruction here. Keep Windows muted.')

    def cancel(self): self.cancelled = True

    def pump(self):
        self.root.update()
        if self.cancelled: raise RuntimeError('Human cancelled the guided hardware test')

    def wait_ready(self):
        while not self.started:
            self.pump()
            time.sleep(.025)

    def show(self, title, text):
        self.title.set(title); self.text.set(text)
        self.pump()

    def issue(self, index, path):
        label, guest, _ = self.plan[index]
        if guest:
            instruction='Keep the game window focused. Press and KEEP HOLDING Cross (×). Wait for CAPTURE NOW before F12. Keep holding until this panel says RELEASE.'
        elif index:
            instruction='RELEASE Cross completely. Leave all controller controls neutral. Wait for CAPTURE NOW before F12.'
        else:
            instruction='Click inside the NEW checkerboard game window. Leave every controller control neutral. Wait for CAPTURE NOW before F12.'
        command=dict(index=index,instruction=instruction,monotonic=time.monotonic(),prompt_source='local guided test panel')
        with path.open('a',encoding='utf-8') as stream: stream.write(json.dumps(command)+'\n')
        title = 'KEEP CONTROLLER NEUTRAL' if index == 0 else ('HOLD CROSS' if guest else 'RELEASE CROSS')
        self.show(f'{index+1}/{len(self.plan)} — {title}',instruction+'\n\nDo not click back to chat while holding a button.')

    def capture(self, index):
        held = bool(self.plan[index][1])
        self.show(f'{index+1}/{len(self.plan)} — F12 NOW',
            ('Keep Cross HELD.' if held else 'Controller UNTOUCHED. No controller button now.')+
            '\n\nClick the game window if needed, then physically send the laptop F12 function key (Fn if needed). '
            'Keep Windows muted.\n\n'+('Do not release Cross before RELEASE appears.' if held else
            ('Wait for UNPLUG USB NOW. Do not press controller buttons or reconnect.' if self.disconnect_mode else
             'Wait until this panel changes. Press Cross only when it says HOLD CROSS.')))

    def disconnect(self, path):
        command=dict(index=1,action='disconnect',instruction='Explicit owner approval received. Unplug the USB cable now; do not reconnect.',
                     monotonic=time.monotonic(),prompt_source='local guided test panel')
        with path.open('a',encoding='utf-8') as stream: stream.write(json.dumps(command)+'\n')
        self.show('UNPLUG USB NOW','The neutral image is verified.\n\nPhysically unplug the DualSense USB cable now. '
                  'Leave it disconnected. Do not press PS or attempt reconnect.\n\nWait for the observed outcome and cleanup.')

    def close_after_disconnect(self):
        self.show('Disconnect observed — close game','SDL observed controller removal. No guest pad-failure marker '
                  'was seen within five seconds.\n\nClose the game window normally with X now. Do not reconnect. '
                  'This observation alone does not verify graceful disconnect support.')

    def finish(self):
        self.show('All five images checked',
            'Controller must stay neutral.\n\nClose the GAME window normally with its X button now. '
            'Leave the controller connected. Do not disconnect or reconnect.\n\nThe test will verify cleanup.')

    def close(self):
        try: self.root.destroy()
        except Exception: pass
