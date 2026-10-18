# Owned engine window-close research

Gate: G4 shutdown increment. The existing pad/VideoOut and AudioOut fixtures can
now request the normal close path of their owned pinned shadPS4 window after
verified guest completion. Two runs of each fixture exited with status zero,
with no active processes in the supervisor's job and no forced termination.
This is engine window-close evidence, not a natural PS4 guest exit or completion
of G4. Hardware audio remains open; the subsequent
[combined fixture](interactive-research.md) exercises graphics/input/PCM together.

## Contract and boundary

Both research runners accept `--shutdown window-close`. Their default remains
`terminate`, because these fixed fixtures deliberately sleep after their PASS
markers. The two registered launch IDs, shortcut behavior, settings and fixed
synthetic probe remain unchanged. No engine or fixture source/patch/hash changes
are needed. Window-close mode requires the updated supervisor built from this
checkout; an older report without the new evidence fields cannot pass it.

After all required guest phase/completion markers and (for pad/VideoOut) three
independently checked Vulkan images, the harness posts one `WM_CLOSE`. It uses
the same owner checks as screenshot/keyboard transport: the supervisor's direct
child must match the exact engine executable path and own exactly one SDL-class
top-level window. It does not select the foreground window, broadcast a close,
kill by executable name or close an unrelated application.

The close request is not a success result. The monitor waits at most eight
seconds after delivery, also bounded by the total attempt deadline. It does not
write `stop.request` for normal close. The supervisor observes the root's exit
and gives Windows Job Object accounting at most 250 ms to settle without
terminating anything. Its additive schema-version-1 fields record:

- `active_before_cleanup`: active processes after that settle interval and
  before any explicit termination.
- `forced_termination`: whether the supervisor needed `TerminateJobObject`.

Window-close verification requires the request's root PID to match the report,
`reason: exited`, integer `exit_code: 0`, `active_before_cleanup: 0`,
`forced_termination: false` and confirmed empty-tree cleanup. A root that exits
zero while leaving a descendant is rejected. Timeouts, monitor failures and
leftover descendants retain the existing bounded Job Object termination path;
closing the supervisor's job handle remains the interruption fallback.

The pinned engine's SDL quit path ends its main event loop and calls
`std::quick_exit(0)`, with its registered shutdown callback. It does not run
every ordinary C++ destructor or establish guest `exit`/`sceKernelExitProcess`
support. The test observes exit/empty-tree behavior, not complete device/resource
teardown or save durability. Audio is still checked from SDL's disk sink after
exit; no audible output or recording device is claimed.

## Reproduce and acceptance

Use the existing strict Windows engine/build report, five fixed homebrew builds,
Vulkan host and updated native supervisor. Build with the normal CMake command
in [development](development.md); Visual Studio places helpers in `Release/`.

```powershell
python tools/run_videoout_research.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/pad-videoout/pad_videoout.oelf --supervisor build/native/ps4-startup-supervisor.exe --profile pad-videoout --shutdown window-close --output build/shutdown/pad-new
python tools/run_audio_research.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/audio-pattern/audio_pattern.oelf --supervisor build/native/ps4-startup-supervisor.exe --shutdown window-close --output build/shutdown/audio-new
python tests/shutdown_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --audio-pattern build/homebrew/audio-pattern/audio_pattern.oelf --output build/shutdown/acceptance-new
```

Choose new output directories. The acceptance script runs two normal closes and
one absent-close negative for each fixture. The negative suppresses only the
host close request: real guest output still completes and is independently
checked, but timeout/forced cleanup must fail lifecycle acceptance. It does not
pretend the engine ignored a delivered request. Separate ordinary Win32 window
tests exercise an actual ignored request and a zero-exit root leaving a child.
The startup suite now has 25 tests, including portable policy/deadline checks,
owned-window normal close, ignored-close fallback, orphan rejection and foreign
window rejection. These host tests alone are not PS4 guest evidence.

All 15 local suites pass. Default-mode actual guest regressions cover all five
fixtures and silent/swapped audio rejection. The existing registered launch CLI
is separately checked for repeated guest execution and input rejection. The
[filtered actual evidence](../research/results/2026-10-18-window-shutdown.json)
records identifiers, output/audit hashes, process reports and validation results.
Complete local data is under `build/shutdown/`; hosted results are listed in the PR.

## Limits and release holds

Windows 11 x86-64 is the tested host; Windows 10, manual close-button usability,
physical controllers, hardware playback, saves
and commercial gameplay remain unverified. Keyboard input and PCM/graphics checks
have the limits in [pad research](pad-research.md) and [audio research](audio-research.md).
Combined graphics/input/PCM evidence is recorded separately in
[interactive research](interactive-research.md).
Existing optional asset/module/Vulkan and dummy service diagnostics remain; SDL's
two disk-driver error-level messages are expected retained sink evidence.

New tools/tests are original GPL-2.0-or-later. No upstream engine or fixture code
is imported into the inspector, and no engine/SDK/fixture/audio/game binaries,
firmware or keys are committed or uploaded. Existing
[dependency/source/relink/runtime/resource holds](release-audit.md) still block
engine redistribution. A supervisor rebuild changes its hash; existing research
registrations correctly require explicit re-registration rather than accepting
an unverified replacement binary.
