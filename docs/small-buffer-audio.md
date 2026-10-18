# Windows small-buffer AudioOut pacing fix

Gate: G4 runtime correctness follow-up to the retained 256-frame audio regression.
The original `audio-pattern` fixture and PCM oracle stay unchanged. This changes
the separately pinned research engine's Windows waits, not the inspector/probe
or the guest's buffer size. All release holds remain open.

## Diagnosis and implementation

Failed captures retained every expected nonzero sample (196,608 interleaved
samples across the two tone phases), but inserted silence between short output
blocks. The preserved old engine reproduced the failure on unchanged main.
This failure is intermittent: later default and child-local timer-hint controls
also passed with the same old executable. The hint alone is not a deterministic
reproducer, and those passes must be retained alongside the original failures.
Minimizing the owned SDL window after actual guest entry supplied a concrete
reproducer on this host: three alternating old/new pairs failed on the old
engine and passed on the patched engine, with the same hint and fixture.
The audio worker uses `Common::AccurateTimer`, whose Windows wait created a
coarse timer. The SDL backend also had an ahead-of-schedule `sleep_for` wait.
Both could overrun the 5.33 ms period of 256 frames at 48 kHz. This is a
measured scheduling weakness consistent with the failed PCM, rather than proof
that every historical dropout had the same cause.

The standalone `tools/windows_wait_probe.py` measured 60 requested 5,333 us waits
on this Windows 11 host. Legacy timer minimum/median/maximum was
14,992.8 / 15,680.85 / 19,348.5 us; the high-resolution timer was
5,451.4 / 5,541.95 / 5,971.9 us. These are actual host-wait diagnostics, not guest
latency, game performance, FPS or a real-time guarantee. Raw samples remain in
`build/small-buffer-wait-probe.json`.

The reviewed patch changes `Common::AccurateSleep` to create a scoped Windows
high-resolution waitable timer. It checks timer creation/arming and closes the
handle on both error and success. The existing interruptible wait and remaining-
duration handling are retained. If an older Windows rejects the high-resolution
flag with `ERROR_INVALID_PARAMETER`, the original coarse timer is the fallback;
that fallback does not promise the small-buffer fix on unsupported Windows.
SDL's Windows ahead-of-schedule path now uses the same wait. Its non-Windows
`sleep_for` path stays unchanged. No global timer-resolution request, busy-spin,
thread-priority increase, device change or new settings knob is added.

Microsoft documents high-resolution waitable timers for Windows 10 version 1803+
in [CreateWaitableTimerExW](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createwaitabletimerexw).
Actual guest validation here is on Windows 11 build 26220, not Windows 10.
Microsoft also documents that Windows 11 may stop honoring a process's higher
timer-period request when its window is minimized or occluded; see
[timeBeginPeriod](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod).
The minimized results are consistent with that behavior. No timer-policy or
power-throttling override is added to the engine.

## Reproduce and acceptance

Preserve the old engine/report and a source archive of its matching main
revision before rebuilding. The comparison must use that archive's unmodified
runner/contract; never bypass the current hash verifier to run the old engine.
Build the new exact strict engine with the normal `tools/build_strict_upstream.py`
recipe in a clean pinned checkout. Existing reviewed cached source may be
incrementally rebuilt only after the new patch/tree contract is verified; an
independent hosted strict build is required separately.

```powershell
python tools/windows_wait_probe.py --iterations 60 --microseconds 5333
python tests/small_buffer_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --baseline-engine build/small-buffer/baseline/shadPS4.exe --baseline-report build/small-buffer/baseline/strict-build.json --baseline-harness build/small-buffer/baseline/sources/tools/run_audio_research.py --retained-baseline build/av-launch/audio-baseline-001 --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --helper build/native/ps4-shortcut-helper.exe --fixture build/homebrew/audio-pattern/audio_pattern.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --interactive-av build/homebrew/interactive-av/interactive_av.oelf --output build/small-buffer/acceptance-new
python tests/small_buffer_window_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --baseline-engine build/small-buffer/baseline/shadPS4.exe --baseline-report build/small-buffer/baseline/strict-build.json --baseline-harness build/small-buffer/baseline/sources/tools/run_audio_research.py --supervisor build/native/ps4-startup-supervisor.exe --fixture build/homebrew/audio-pattern/audio_pattern.oelf --output build/small-buffer/minimized-acceptance-new
```

Choose a new output directory. Acceptance first rechecks the retained baseline's
actual PCM with the unchanged oracle, matching engine/fixture/audit hashes and
guest completion/cleanup. It records two new preserved-engine controls,
then requires five consecutive patched 256-frame successes under coarse-timer
control, two default-environment successes, genuine silent/swapped guest rejection,
all 28 earlier Windows/disk/volume outcomes and all nine registered CLI/Shell/
settings outcomes: **46 patched expected outcomes**. All
guest cases retain strict entry/import checks and bounded tree cleanup; the
focused audio cases require normal engine close. The same source/ELF hashes,
3–12 second audio bound, Goertzel/RMS thresholds and ordered signal windows apply.
Existing 2,048-frame fixtures do not substitute for the 256-frame cases.

SDL normally requests a 1 ms timer period. To remove that optional request,
the comparison sets the documented
[`SDL_TIMER_RESOLUTION=0`](https://wiki.libsdl.org/SDL3/SDL_HINT_TIMER_RESOLUTION)
in each controlled child only, suppressing SDL's optional timer-period request.
The old archived runner receives that same child environment, without source
changes. Patched controlled cases use the research-only `--coarse-timer-test`
option; normal runs retain inheritance. This neither changes the parent/global
timer state nor edits PCM/guest code. The parent-environment invariant has a
portable test. Both engines receive the same hint, which does not establish the
actual Windows timer resolution or suppress requests by other components. The
retained old signal failure must be independently reverified; new baseline runs
are reported whether they pass or fail. All five new controlled runs must pass
unchanged signal checks. No requirement is satisfied by editing captured PCM.

Local results, exact source/patch/tree/executable/fixture/output hashes and final
hosted build/log/artifact review are reported separately in the PR. Source builds
and host tests are not guest execution. Native AAC/linkage checks remain required
because the shared engine is rebuilt. Existing registrations must be explicitly
replaced after a verified rebuild; changed binary/report hashes cannot be accepted
silently.

The fresh local `build/small-buffer/acceptance-005` matrix passed all **46**
patched expected outcomes: seven focused positives, two real negative outputs,
28 earlier volume/Windows/disk cases and nine registered CLI/Shell/settings
launches. The audio-only case at the end of the nested earlier matrix passed
with 220,160 frames. All 17 local host suites passed. The seven focused positives
and two negative cases all completed with normal zero exit and empty process
trees; earlier hello/service fixtures retain their documented bounded termination.
Captured PCM/audit/image hashes were independently cross-checked after the run.
The 48 engine logs (including two new old-engine controls) added no warning/error
patterns relative to the retained PR #26 acceptance/regression logs. This is
fixture-specific verification on this host, not a general timing guarantee.
The independent hosted strict source build and its artifact review remain
pending until recorded in the PR and filtered result.

The supplemental `build/small-buffer/minimized-acceptance-002` alternates three
preserved and three patched engine runs. Its test worker uses the existing
supervisor/path/window ownership checks before `ShowWindowAsync(SW_MINIMIZE)`,
waits for actual guest entry so SDL initialization cannot restore the window,
and independently observes `IsIconic`. It neither edits the archived runner nor
changes the PCM oracle. Both versions receive `SDL_TIMER_RESOLUTION=0`.

| Alternating pair | Old PCM frames / result | Patched PCM frames / result |
| --- | --- | --- |
| 0 | 590,848 / rejected | 221,184 / passed |
| 1 | 592,896 / rejected | 220,160 / passed |
| 2 | 593,920 / rejected | 220,160 / passed |

Each old capture exceeds the original 576,000-frame maximum; every capture
retains 196,608 nonzero interleaved samples. All six guests enter with zero
unresolved imports, complete their fixture calls and close normally with empty
process trees. These are recorded frame counts, not audio-latency or game
performance measurements. Together with the main matrix, **49 patched guest
expected outcomes pass**, with three contemporaneous old-engine failures.
The first exploratory worker minimized during SDL initialization and failed
to observe the minimized state; that transport attempt is retained separately
and is not counted as a guest signal result.

The minimized cases also expose two `signals.cpp` critical diagnostics for
exception `0xe06d7363` in **each preserved and patched run**. The guest subsequently
completes all phases and the process exits with zero status and an empty tree.
These diagnostics are additional to the ordinary-window logs; their origin is
unresolved and they are not described as harmless. They are unchanged between
the paired engines, rather than a new wait-patch regression. This audio timing
comparison does not establish clean general minimized rendering or shutdown.

## Limits and licensing

This does not prove arbitrary-load hard real-time behavior, acoustic output,
256-frame hardware playback, physical controllers, new formats/codecs, commercial
gameplay or complete G4. The combined 2,048-frame Windows-render cases are
regressions, not a 256-frame hardware result. The earlier exploratory concurrent
256-frame fixture is not repinned or declared fixed by a standalone fixture.
Windows timer-creation failure/fallback and Windows 10 guest behavior remain
unverified on hardware. Ordinary Linux host checks remain useful; Linux guest
engine timing is not claimed tested.

The upstream source retains its existing GPL-2.0-or-later attribution. The small
patch and new original probe/test code introduce no third-party code/dependency.
No engine/SDK/fixture/game/audio binary, firmware or key is committed/uploaded.
The [source/relink/runtime/resource holds](release-audit.md) still block engine
redistribution. There is no installer or distribution approval.
