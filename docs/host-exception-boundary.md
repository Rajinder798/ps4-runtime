# Windows host C++ exception boundary

Gate: G4 runtime correctness prerequisite for stable minimized-window shutdown.
This work changes only the separately pinned research engine. The original
inspector/probe, guest fixtures, PCM thresholds and Windows launch contract are
unchanged. Engine redistribution remains blocked by the separate release audit.

## Problem and scoped change

The [small-buffer audio comparison](small-buffer-audio.md) recorded two critical
`0xe06d7363` diagnostics per minimized session, in both engines, even though the
guest continued and the process eventually closed normally. The Windows vectored
handler logged these as unhandled and called `Emulator::Shutdown()`, which closes
the database and stops lifecycle workers. This was premature: a vectored handler
runs before stack-based exception handlers. Microsoft identifies this code as
the MSVC C++ exception code; it does not by itself establish an unhandled fault.
See [vectored exception handling](https://learn.microsoft.com/en-us/windows/win32/debug/vectored-exception-handling)
and [specific exception codes](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/specific-exceptions).

The patch returns `EXCEPTION_CONTINUE_SEARCH` for that exact code only when
`g_curthread` is null. This leaves Windows to find a C++ catch handler or perform
ordinary native unhandled-exception termination. An informational diagnostic
records that the host-thread path was taken. The separate legacy thread-name
exception `0x406d1388`, guest-marked threads, access violations, illegal
instructions and Linux paths retain their existing behavior. The absence of a
guest marker is the scope guard, not a claim that every host throw is harmless.

## Acceptance and reproduction

The native driver installs a real Windows vectored observer using the same
classifier embedded in the engine patch. It throws/catches actual C++ values,
checks host versus guest-marker routing, compares uncaught termination with a
child having no observer, and triggers a real inaccessible-page read. These are
host boundary tests, not PS4 guest-fault execution or the engine's shutdown code.
The strict Windows build runs them alongside AAC and linkage checks and uploads
JSON/compiler evidence without test executables or engine binaries.

```powershell
python tools/test_host_exception_boundary.py --source build/upstream/shadps4-strict --output build/host-exception/native-new
python tests/host_exception_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --baseline-engine build/host-exception/baseline/shadPS4.exe --baseline-report build/host-exception/baseline/strict-build.json --baseline-harness build/host-exception/baseline/sources/tools/run_audio_research.py --supervisor build/native/ps4-startup-supervisor.exe --fixture build/homebrew/audio-pattern/audio_pattern.oelf --output build/host-exception/minimized-new
```

Preserve the current main engine, strict report and matching source archive
before rebuilding. Both sides must pass their own unchanged hash contract.
The minimized test reuses the existing owned-window transport: wait for real
guest entry, request minimization, observe `IsIconic`, then use the runner's
normal window close. Three alternating pairs must pass the unchanged 256-frame
PCM oracle, guest completion, zero normal exit and empty process-tree checks.
The baseline must reproduce the C++ critical diagnostic; the patched engine
must record host deferral without critical diagnostics. A run that does not
reproduce the baseline condition is retained as inconclusive, never called a
successful comparison.

## Validation status

Local Windows native boundary tests and all 17 local Windows host suites pass.
Hosted Windows/Linux host checks also pass at implementation commit `2a2e604`.
Three alternating minimized pairs pass: every capture contains 221,184 frames;
all six guests enter with zero unresolved imports, complete and close normally
with zero status and empty process trees. Every baseline log has two critical
C++ diagnostics; every patched log instead has two host-deferral messages and
no critical diagnostics. This establishes the guarded host-thread branch for
the observed throws, without identifying which library originated them.

The baseline is merged main `8cfd8187a6104ce6d72289a77b3918e8edfe190f`,
engine SHA-256 `994fab59088d3d2509d3fc4ded3ec53029b0ffc2f532d1ba7d1a53e1e219191b`.
The local patched executable is
`c41da6f5a27a8215b816c2215c3c830c6726d461f44791423f49daec9f0571ba`,
patch `1927fd9f7a4abdc455c3b1bfc60235699146f245d6370cd9afa0611acb68ecce`,
tree `854265c186681c230ae049e86ba7cb335e6c20ea`. Header/fixture pins are
unchanged. Local evidence is under `build/host-exception/minimized-002` and
`build/host-exception/native-002`. The first comparison attempt retained a
successful baseline guest but stopped on an incorrect new harness status check
(`completed` instead of the existing `passed`); it is not counted in the pairs.

The actual native uncaught C++ reference exits `0xc0000409` on this CRT; both
observed uncaught paths match it. The inaccessible-page child exits
`0xc0000005`. The initial native test incorrectly expected the C++ throw code
as the final exit status; the corrected test measures ordinary uncaught
termination in a reference child before comparing the observed paths.

The existing 28-case audio regression matrix passes on the patched engine,
including Windows-rendered PCM, disk PCM, full/half/mute/restored gain,
silent/swapped rejection and all earlier six-fixture regressions. Nine saved
volume launches, nine prior registered launches and six legacy Settings/UI
launches also pass, including existing Shell shortcuts. There are **55 patched
expected guest outcomes**: those 52 regressions plus three minimized runs;
three baseline minimized runs are separate comparison evidence. The ordinary
engine logs add no warning/error patterns relative to the prior volume matrix.
The [filtered result](../research/results/2026-10-19-host-exception-boundary.json)
retains identities, native results, paired diagnostics, frame counts and raw
summary/result/audit/PCM hashes. Raw regression outputs are under
`build/host-exception/{audio-regressions-001,volume-settings-001,
registered-regressions-001,legacy-settings-001}`. Reproduce these with the existing
`tests/audio_volume_guest_tests.py`, `tests/av_volume_settings_guest_tests.py`,
`tests/av_launch_guest_tests.py` and `tests/settings_guest_tests.py --settings-ui`
commands documented in their corresponding audio/launch/settings guides, using
the new engine/report and fresh output directories.

The independent hosted strict build and its artifact/compiler-warning review
remain pending: [run 39172527522](https://github.com/Rajinder798/ps4-runtime/actions/runs/39172527522).
The [PR host checks](https://github.com/Rajinder798/ps4-runtime/actions/runs/39172553212)
and [push host checks](https://github.com/Rajinder798/ps4-runtime/actions/runs/39172527493)
both pass all 17 suites on Windows and Linux. Their only build warning is the
existing Windows multi-config unused `CMAKE_BUILD_TYPE`. The unchanged fixture
and FFmpeg inputs retain their prior verified build/provenance evidence; this
patch adds no dependency. A completed independent engine rebuild is required
before requesting merge review. The PR remains a draft.

This does not establish the underlying library's reason for throwing, acoustic
output, manual gameplay, natural guest exit, arbitrary guest-fault delivery,
Windows 10 hardware behavior, general compatibility or full G4. No dependency,
guest input, firmware, key or third-party binary is introduced. Existing upstream
GPL attribution and all [release/source/relink holds](release-audit.md) remain.
