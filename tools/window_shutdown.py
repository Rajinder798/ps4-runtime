# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Bounded close request after fixture evidence; no guest-exit claim."""
import time

GRACE_SECONDS = 8


class WindowClose:
    def __init__(self):
        self.request = None
        self.began = None

    def poll(self, ready, supervisor_pid, engine):
        if self.request is None and ready:
            from videoout_capture import request_close
            self.request = request_close(supervisor_pid, engine)
            self.began = time.monotonic()
        if self.began is not None and time.monotonic() - self.began > GRACE_SECONDS:
            raise ValueError("Engine did not exit within the window-close grace period")
        # Do not create stop.request. The engine must exit through its own handler.
        return False

    def verify(self, transport):
        if (self.request is None or self.request.get("transport") != "owned SDL window WM_CLOSE" or
                type(self.request.get("root_pid")) is not int or
                self.request["root_pid"] != transport.get("root_pid") or
                transport.get("reason") != "exited" or type(transport.get("exit_code")) is not int or transport["exit_code"] != 0 or
                transport.get("tree_cleanup") is not True or transport.get("forced_termination") is not False or
                type(transport.get("active_before_cleanup")) is not int or transport["active_before_cleanup"] != 0):
            raise ValueError("Window close did not produce a zero exit with an independently empty process tree")
        return dict(**self.request, grace_seconds=GRACE_SECONDS, verified=True)
