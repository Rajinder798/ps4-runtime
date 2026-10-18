# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Optional settings window; never starts a guest or participates in normal launch."""
import argparse
from pathlib import Path
import sys

import ps4_launch as launcher
import runtime_settings as settings

SCOPES = ("All supported titles", "Hello world", "Service roundtrip", "Graphics, input and audio self-test")
TITLES = (None, *launcher.PROFILES)
LEVELS = ("Debug", "Info", "Warning")
VOLUMES = ("Mute (0%)", "Half (50%)", "Full (100%)")


class SettingsWindow:
    def __init__(self, root, home, title=None):
        # Keep Tk optional for the launch CLI and Python installations without it.
        import tkinter as tk
        from tkinter import ttk

        self.root, self.home = root, Path(home).resolve()
        root.title("PS4 Runtime Settings")
        root.minsize(660, 610)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=24)
        body.grid(sticky="nsew")
        body.columnconfigure(0, weight=1)
        ttk.Label(body, text="Preferences", font=("Segoe UI", 18)).grid(sticky="w")
        ttk.Label(body, text="Preferences for supported research homebrew titles.").grid(sticky="w", pady=(4, 18))
        ttk.Label(body, text="Apply to").grid(sticky="w")
        self.scope = ttk.Combobox(body, values=SCOPES, state="readonly")
        self.scope.grid(sticky="ew", pady=(4, 16))
        self.scope.current(TITLES.index(title))
        self.scope.bind("<<ComboboxSelected>>", lambda event: self.refresh())
        ttk.Label(body, text="Diagnostic log level").grid(sticky="w")
        self.level = ttk.Combobox(body, state="readonly")
        self.level.grid(sticky="ew", pady=(4, 6))
        self.level.bind("<<ComboboxSelected>>", lambda event: self.changed())
        ttk.Label(body, text="Debug: detailed logs · Info: normal logs · Warning: warnings and errors").grid(sticky="w")
        ttk.Label(body, text="Audio volume").grid(sticky="w", pady=(16, 0))
        self.volume = ttk.Combobox(body, state="readonly")
        self.volume.grid(sticky="ew", pady=(4, 6))
        self.volume.bind("<<ComboboxSelected>>", lambda event: self.changed())
        ttk.Label(body, text="Applies to the graphics, input and audio self-test. Other titles have no audio control.",
                  wraplength=600).grid(sticky="w")
        self.effective = tk.StringVar(root)
        ttk.Label(body, textvariable=self.effective, wraplength=600).grid(sticky="w", pady=(14, 16))
        actions = ttk.Frame(body)
        actions.grid(sticky="ew")
        self.save_button = ttk.Button(actions, text="Save", command=self.save)
        self.save_button.pack(side="left")
        self.reset_button = ttk.Button(actions, text="Reset this scope", command=self.reset)
        self.reset_button.pack(side="left", padx=8)
        self.reset_all_button = ttk.Button(actions, text="Reset all scopes", command=self.reset_all)
        self.reset_all_button.pack(side="left")
        self.refresh_button = ttk.Button(actions, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="right")
        ttk.Label(body, text="Changes apply to the next launch. Switching scope or Refresh discards unsaved edits.",
                  wraplength=600).grid(sticky="w", pady=(12, 12))
        self.status = tk.StringVar(root)
        self.status_label = ttk.Label(body, textvariable=self.status, wraplength=600)
        self.status_label.grid(sticky="ew", pady=(0, 16))
        ttk.Separator(body).grid(sticky="ew")
        ttk.Label(body, text="Preferences folder").grid(sticky="w", pady=(12, 4))
        self.location = tk.StringVar(root, value=str(self.home))
        self.location_entry = ttk.Entry(body, textvariable=self.location, state="readonly")
        self.location_entry.grid(sticky="ew")
        self.refresh()
        self.scope.focus_set()

    @property
    def title(self):
        return TITLES[self.scope.current()]

    def message(self, text, error=False):
        self.status.set(text)
        self.status_label.configure(foreground="#a32121" if error else "")

    def render(self, result, message):
        title = self.title
        inherited = "Use default (Info)" if title is None else "Inherit global preference"
        self.level.configure(values=(inherited, *LEVELS), state="readonly")
        stored = result["settings"]["global"] if title is None else result["settings"]["titles"].get(title, {})
        level = stored.get("log_level")
        self.saved_index = LEVELS.index(level.title()) + 1 if level else 0
        self.level.current(self.saved_index)
        volume = stored.get("volume_percent")
        self.saved_volume_index = settings.VOLUME_LEVELS.index(volume) + 1 if volume is not None else 0
        self.audio_available = "volume_percent" in result["defaults"]
        if self.audio_available:
            self.volume.configure(values=(("Use default (Full)" if title is None else "Inherit global preference"), *VOLUMES), state="readonly")
            self.volume.current(self.saved_volume_index)
        else:
            self.volume.set("Not available for this title")
            self.volume.configure(state="disabled")
        value = result["effective_settings"]["log_level"].title()
        source = {"default": "default", "global": "global preference", "title": "title override"}[result["settings_sources"]["log_level"]]
        self.effective.set(f"Saved for next launch: {value} (from {source})")
        if self.audio_available:
            percent = result["effective_settings"]["volume_percent"]
            source = result["settings_sources"]["volume_percent"]
            self.effective.set(self.effective.get() + f"; Volume {percent}% (from {source})")
        self.save_button.state(["disabled"])
        self.reset_button.state(["!disabled"])
        self.reset_all_button.state(["!disabled"])
        self.message(message)

    def refresh(self):
        try:
            result = settings.inspect(self.home, launcher.PROFILES, self.title)
        except settings.SettingsError as error:
            self.level.set("")
            self.level.configure(state="disabled")
            self.volume.set("")
            self.volume.configure(state="disabled")
            for button in (self.save_button, self.reset_button, self.reset_all_button):
                button.state(["disabled"])
            self.effective.set("Saved preferences unavailable. Resolve the error, then Refresh.")
            self.message(f"{error.code}: {error}", error=True)
            return
        self.render(result, "Preferences loaded.")

    def changed(self):
        changed = (self.level.current() != self.saved_index or
                   (self.audio_available and self.volume.current() != self.saved_volume_index))
        self.save_button.state(["!disabled" if changed else "disabled"])
        self.message("Selection not saved." if changed else "Preferences loaded.")

    def update(self, **kwargs):
        try:
            result = settings.update(self.home, launcher.PROFILES, **kwargs)
        except settings.SettingsError as error:
            # A read/modify/write revalidates current disk contents, even when the
            # window's last snapshot was valid. Never overwrite invalid state.
            if error.code == "invalid_settings":
                self.refresh()
            self.message(f"{error.code}: {error}", error=True)
            return
        # reset_all returns a global snapshot; resolve the current title from the
        # same document without a second disk read/race with an external writer.
        result = settings.describe(result["settings"], self.title)
        self.render(result, "Saved. Applies to the next launch.")

    def save(self):
        index = self.level.current()
        changes = {}
        if index != self.saved_index and index in range(len(LEVELS) + 1):
            changes["log_level"] = None if index == 0 else LEVELS[index - 1].lower()
        volume = self.volume.current()
        if self.audio_available and volume != self.saved_volume_index and volume in range(len(VOLUMES) + 1):
            changes["volume_percent"] = None if volume == 0 else settings.VOLUME_LEVELS[volume - 1]
        if changes:
            self.update(title=self.title, changes=changes)

    def reset(self):
        self.update(title=self.title, reset=True)

    def reset_all(self):
        self.update(reset_all=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=launcher.default_home())
    parser.add_argument("--title", choices=launcher.PROFILES)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The optional Settings window currently supports Windows only")
    try:
        import tkinter as tk
    except ImportError:
        unavailable()
        return 4
    try:
        root = tk.Tk()
    except tk.TclError:
        unavailable()
        return 4
    SettingsWindow(root, args.state_dir, args.title)
    root.mainloop()
    return 0


def unavailable():
    # A pythonw entry must surface a missing Tk prerequisite without a console.
    import ctypes
    dialog = ctypes.windll.user32.MessageBoxW
    dialog.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
    dialog.restype = ctypes.c_int
    dialog(None, "Could not open Settings. Use a Python installation with working Tcl/Tk support.",
           "PS4 Runtime Settings unavailable", 0x10)


if __name__ == "__main__":
    raise SystemExit(main())
