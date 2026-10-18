# Registered graphics, input and audio self-test

Gate: G3 source-based Windows launch increment using the verified G4 fixture.
The reviewed `interactive-av` homebrew can be registered once and launched by
name or Windows shortcut. This is an **automated self-test**: the host sends the
known neutral/Cross/release sequence, verifies guest output and closes the window.
It is not a manually controlled game or a claim of full G4 completion.

## Register and launch

Use the existing pinned strict engine, combined fixture and native helpers, this
source checkout, Python 3.12+ with matching `pythonw.exe`, Vulkan and an active
default audio render endpoint. This profile requires Windows process loopback
(build 20348+); ordinary Windows 10 build 19045 is unsupported for this profile.
Actual validation is on Windows 11 build 26220. See [Windows audio research](windows-audio-research.md).

```powershell
python tools/ps4_launch.py --state-dir build/launch/av-local register --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --interactive-av build/homebrew/interactive-av/interactive_av.oelf --capture-helper build/native/ps4-process-audio-capture.exe --json
python tools/ps4_launch.py --state-dir build/launch/av-local launch interactive-av --json
python tools/ps4_launch.py --state-dir build/launch/av-local shortcut interactive-av --directory build/shortcuts/av-local --helper build/native/ps4-shortcut-helper.exe --json
```

Open `PS4 Runtime - interactive-av.lnk` normally in Explorer. Successful runs have
no setup/success prompt. Failures use the existing error dialog and saved result.
The console-free source entry launches separately; no guest code runs in Explorer.
The small test window and tones are expected. No physical controller is needed.
Supervisor, capture-helper and Vulkan-diagnostic subprocesses use Windows
`CREATE_NO_WINDOW`, preserving file/pipe diagnostics without helper consoles.
Supervisor errors now include the exit code and whether a report was produced.
Development found an empty-report failure with exit 3221225786 (`0xC000013A`),
which Microsoft identifies as console-control termination. The originating
control-event sender was not identified; it is not evidence of a guest crash.
See [NTSTATUS values](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55)
and [process flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags).

## Registration and completion contract

Existing hello/service registrations remain schema 1 with unchanged completion
behavior. AV registration uses schema 2, adding the absolute capture-helper path
and SHA-256. `--interactive-av` and `--capture-helper` must be supplied together.
Unknown fields/versions, malformed records and schema-1 AV entries fail. Adding
AV to existing state requires explicit `register --replace` with **all desired
fixture paths**, including old hello/service paths when they should remain
registered. There is no silent migration/replacement; failed updates preserve
the previous file. Older source cannot read schema 2 or silently downgrade it.

Each AV launch rechecks engine/report/supervisor/fixture/helper hashes and the
current strict research contract before session allocation. Legacy launches do
not require an unselected AV helper/fixture to remain present. Helpers are trusted
owner-registered executables; hashes detect changes, not authenticity or sandboxing.
Use helpers built from reviewed project source.

Each fresh session generates challenges/configuration automatically. Validated
global/per-title `log_level` applies to that engine session. The optional Settings
window adds **Graphics, input and audio self-test** as a diagnostic scope; no
audio setting/control is added. Normal launches never import/open Tk. Strict
audit and guest checks remain independent of log filtering.

The schema-1 launch response gains AV verification fields,
`input_source: automated_keyboard_sequence` and `hardware_playback_tested: false`.
Only strict guest entry/zero unresolved imports, three checked Vulkan images,
actual guest pad records, owned-process Windows-rendered PCM and normal engine
close grant `status: completed`, `completion: fixture_observed_and_window_closed`.
Device/API/signal/input/image/close failures never fall back to disk-only success.
The AV observation budget is 45 seconds; hello/service retain their original
`fixture_observed_and_stopped` bounded termination contract.

Unique sessions retain `launch-result.json`, `videoout-result.json`, Vulkan
diagnostics, audit, screenshots, pad records and raw owned-process PCM. No other
application/microphone capture or upload is added. Logs/PCM stay local until
manually removed. Launches preserve registration, links and earlier evidence.

## Reproduce and verify

```powershell
python tests/av_launch_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --helper build/native/ps4-shortcut-helper.exe --output build/av-launch/acceptance-new
```

Choose a new output directory. The matrix checks two legacy schema-1 runs, failed
and explicit registration upgrade, five AV runs (three CLI/two actual Shell)
across default/global/title/reset preferences using real optional Tk controls,
then an existing legacy shortcut and service launch after upgrade. It checks nine
unique sessions, preserved earlier evidence and unchanged registration/link
bytes. Tampered AV/helper copies must fail before execution/session allocation.
Original inputs are never modified. Separately rerun
`tests/audio_volume_guest_tests.py` for all 28 earlier expected guest outcomes.

The existing 17 host suites include four new portable launch tests for schema/
upgrade/helper recheck/all-surface dispatch/CLI rejection, plus a Windows real-Tk
AV diagnostic scope save/reopen test. Linux skips the graphical tests explicitly.
The startup suite also checks that a real background child has no console while
stdout/stderr diagnostics remain intact; Job Object lifetime checks still apply.
Hosted policy tests do not run guests or open audio. Local actual-guest results,
filtered identifiers and final hosted results are recorded separately in the PR.

The [filtered local evidence](../research/results/2026-10-18-av-self-test-launch.json)
records **nine registered launches passed** and **17/17 host suites passed**.
Both full regression attempts passed 27/28 expected outcomes and failed the older
audio-only case described below. This work remains a draft pending that baseline
issue; hosted contract success does not override the guest failure. Raw launch
evidence is in `build/av-launch/acceptance-005`; the final repeat is in
`build/av-launch/regressions-002` with the unchanged-main comparison retained.

## Limits and licensing/security review

The regression follow-up observed one failed **256-frame audio-only** disk
capture: guest calls and normal close completed, but neither stereo tone had a
qualifying window. The unchanged merged-main runner reproduced this failure
with the same verified engine/fixture/supervisor inputs; an isolated branch
recheck passed. This establishes a baseline problem, not its timing cause or
general reliability. Failed raw captures are retained. The AV self-test uses
the unchanged 2,048-frame combined fixture and passed its five registered runs;
the audio oracle is not weakened to accept the older failure.

Source/Python and separately built research inputs remain required. Installed G3,
full G4, natural guest exit, acoustic output, manual gameplay, physical controller
support, saves and commercial compatibility remain unverified. Three reviewed
registered homebrew IDs do not establish arbitrary-ELF/game support. The original
inspector/fixed probe is unchanged.

Engine/fixture/patch/header/dependency pins are unchanged. Original additions use
GPL-2.0-or-later with no third-party code/dependency import. No engine/SDK/game/
fixture/audio binary, firmware or key is committed/uploaded. All [release holds](release-audit.md)
remain; no installer, engine bundle or redistribution approval is produced.
