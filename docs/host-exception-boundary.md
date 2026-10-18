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

Local Windows native boundary tests pass. Actual minimized guest comparison,
full guest regressions, Windows/Linux host tests and independent hosted strict
build remain pending. No clean minimized-window capability is claimed yet.

This does not establish the underlying library's reason for throwing, acoustic
output, manual gameplay, natural guest exit, arbitrary guest-fault delivery,
Windows 10 hardware behavior, general compatibility or full G4. No dependency,
guest input, firmware, key or third-party binary is introduced. Existing upstream
GPL attribution and all [release/source/relink holds](release-audit.md) remain.
