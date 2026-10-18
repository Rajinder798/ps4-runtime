# Windows small-buffer AudioOut pacing fix

Gate: G4 runtime correctness follow-up to the retained 256-frame audio regression.
The original `audio-pattern` fixture and PCM oracle stay unchanged. This changes
the separately pinned research engine's Windows waits, not the inspector/probe
or the guest's buffer size. All release holds remain open.

## Cause and implementation

Failed captures retained every expected nonzero sample (196,608 interleaved
samples across the two tone phases), but inserted silence between short output
blocks. The preserved old engine reproduced the failure on unchanged main.
The audio worker uses `Common::AccurateTimer`, whose Windows wait created a
coarse timer. The SDL backend also had an ahead-of-schedule `sleep_for` wait.
Both could overrun the 5.33 ms period of 256 frames at 48 kHz.

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
python tests/small_buffer_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --baseline-engine build/small-buffer/baseline/shadPS4.exe --baseline-report build/small-buffer/baseline/strict-build.json --baseline-harness build/small-buffer/baseline/sources/tools/run_audio_research.py --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --helper build/native/ps4-shortcut-helper.exe --fixture build/homebrew/audio-pattern/audio_pattern.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --videoout-pattern build/homebrew/videoout-pattern/videoout_pattern.oelf --pad-videoout build/homebrew/pad-videoout/pad_videoout.oelf --interactive-av build/homebrew/interactive-av/interactive_av.oelf --output build/small-buffer/acceptance-new
```

Choose a new output directory. Acceptance records two preserved-engine controls,
then requires five consecutive patched 256-frame successes, genuine silent/
swapped guest rejection, all 28 earlier Windows/disk/volume outcomes and all nine
registered CLI/Shell/settings outcomes: **44 patched expected outcomes**. All
guest cases retain strict entry/import checks and bounded tree cleanup; the
focused audio cases require normal engine close. The same source/ELF hashes,
3–12 second audio bound, Goertzel/RMS thresholds and ordered signal windows apply.
Existing 2,048-frame fixtures do not substitute for the 256-frame cases.

Local results, exact source/patch/tree/executable/fixture/output hashes and final
hosted build/log/artifact review are reported separately in the PR. Source builds
and host tests are not guest execution. Native AAC/linkage checks remain required
because the shared engine is rebuilt. Existing registrations must be explicitly
replaced after a verified rebuild; changed binary/report hashes cannot be accepted
silently.

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
