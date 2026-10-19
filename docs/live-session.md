# User-closed live homebrew sessions

Gate: a G3 launch-lifetime prerequisite using the existing G4 `live-av` fixture.
The ordinary source command runs until the engine window closes. It requires
neither gameplay cycles nor audio capture to accept a normal close. This is a
prerequisite for registering a live shortcut; existing registered profiles and
their finite self-test completion contracts remain unchanged.

## Run locally

Use the exact pinned strict engine/report and seventh original fixture from
[live AV research](live-av-research.md). A physical controller is not required.
The reviewed keyboard mapping uses N for Cross and B for Circle. Focus the SDL
window to interact, and close it to end the session.

```powershell
python tools/run_live_session.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --output build/live-session/manual-new
```

There is a 30-second startup-readiness budget (configurable from 3 to 30 seconds),
then no fixed total session duration. The strict audit and 64 MiB output limits
remain enforced, as does the unchanged guest's 128-observation limit. This is
not a claim of unlimited arbitrary software support. Vulkan and working WASAPI
rendering remain engine dependencies. The ordinary runner requires no loopback
capture helper, `vulkaninfo`, screenshot requests, input injection or automatic
window-close requests. It uses a fresh isolated profile at volume 100; persistent
settings and registered live shortcuts are subsequent integration work.

`session-status.json` records host transport ownership and validated guest
readiness/observations for diagnostics. `session-result.json` reports `closed`
only after strict entry/readiness, a zero engine exit and an independently empty
process tree without forced cleanup. Closing without pressing any key is valid.
Readiness and normal host exit are not natural guest completion or independent
graphics/input/audio qualification; the corresponding result fields remain false.
The old `run_live_av.py` probe still requires its full bounded qualification.

## Lifetime and containment

Numeric supervisor timeouts retain the existing 100–120000 millisecond contract.
The additive internal `until-exit:<handle>` mode requires a real inherited process
handle identifying its live launcher parent. Python explicitly inherits only that
handle and standard redirected streams, then closes its local handle copy. The
supervisor clears inheritability and passes only its three stream handles to the
engine. A process handle identifies the original process object throughout its
lifetime; the supervisor never reopens an owner PID after launch.

The supervisor watches that owner handle, root exit and explicit stop requests.
Launcher death produces `owner_exited` and bounded Job Object cleanup. Supervisor
death closes its kill-on-close Job Object. The engine is atomically assigned to
the Job Object at creation; root exit with surviving descendants still requires
forced cleanup and cannot qualify as normal close. Reports in the new mode add
`lifetime: until_exit` and `owner_watch_verified: true` to schema 1.

The explicit inherited handle follows [Python's Windows handle-list contract](https://docs.python.org/3.12/library/subprocess.html#subprocess.STARTUPINFO).
The native check uses [GetProcessId](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocessid)
and this supervisor's [parent process entry](https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w).
Do not embed the temporary inheritable-handle section in a host that concurrently
spawns children inheriting all handles; the command uses explicit handle lists.

## Acceptance and reproduction

```powershell
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
python tests/live_session_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --output build/live-session/acceptance-new
```

Build helpers before running guest matrices; never relink binaries in use.
The portable nineteenth suite covers rejected output/startup budgets, missing
inputs and truthful postmortem entry evidence. Real Windows process tests cover
new-mode normal exit, requested stop, owner death with descendants and invalid
owner rejection, alongside the existing timed/abrupt-helper-exit cases.

The opt-in guest matrix checks normal no-input close, responsiveness after 125
seconds of readiness, abrupt launcher death and explicit stop. Only this external
test driver requests input, screenshots and close. After the old cutoff, it
independently checks five sequence-bound Vulkan images, guest-written input
records and two sustained Windows-rendered tone cycles using the unchanged
oracles. Its bounded process-loopback qualification needs Windows build 20348+;
that diagnostic dependency is absent from the ordinary runner.

All four actual guest expected outcomes pass in
`build/live-session/acceptance-002`. In the long case, the first external Cross
press occurs 126.843 seconds after validated readiness; the strict guest observes
it at 129.016 seconds after engine audit startup. Five 640×360 readbacks, matching
guest-written records and sustained silence/tone/silence/tone/silence Windows PCM
qualify the response after the old limit. Normal close leaves zero active job
processes without forced cleanup. The no-input close creates no PNG/raw captures.
Launcher death and stop both terminate the owned tree and are never successful
ordinary-session closes.

All 60 earlier guest expected outcomes also pass against the final native helper:
eight live AV, 28 audio/earlier-fixture, nine saved-volume, nine registered-launch
and six legacy settings cases. All 19 local Windows host suites pass, including
30 startup tests. The implementation commit's hosted
[PR](https://github.com/Rajinder798/ps4-runtime/actions/runs/39196820909) and
[push](https://github.com/Rajinder798/ps4-runtime/actions/runs/39196791137) workflows
pass 19 suites on each Windows/Linux host. Reviewed logs have no compiler warnings
or new material engine diagnostic patterns; the existing Windows multi-config
CMake unused-build-type warning remains.

The unchanged seven fixture inputs were independently rebuilt on merged main in
[39195790321](https://github.com/Rajinder798/ps4-runtime/actions/runs/39195790321):
all converted ELF/source hashes match, with zero compiler warnings and seven
existing CMake warnings. The exact unchanged engine inputs reuse the reviewed
[strict build 39192608940](https://github.com/Rajinder798/ps4-runtime/actions/runs/39192608940),
whose native tests and existing upstream/dependency warnings were reviewed in
the preceding increment. Neither source build is guest execution evidence.

[Machine-readable evidence](../research/results/2026-10-19-live-session.json)
records source/helper/fixture/audit/PCM/image hashes, host/toolchain, commands,
all 64 expected outcomes and limitations. An initial external-parent capture
attempt was rejected by the existing sibling-parent ownership gate after 125
seconds; its forced stop cleaned the tree. That attempt is retained but excluded
from passing acceptance. The corrected test host adds capture as the supervisor's
sibling, with no change to the capture ownership gate or ordinary runner. Final
commit hosted checks are reported in the PR after completion.

Hosted unit/source builds do not establish guest behavior.
Human keyboard usability, acoustic output, Windows 10 behavior, natural guest
exit, physical controllers, installed G3, full G4 and commercial gameplay remain
unverified. The fixture/engine pins and separate license/source/relink release
holds are unchanged. No engine, SDK, fixture binaries or captured media are
distributed by this increment; original new code is GPL-2.0-or-later.
