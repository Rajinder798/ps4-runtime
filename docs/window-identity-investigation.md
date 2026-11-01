# Bound-window identity investigation — issue #39

Gate: G4 test observability, based on verified `main`
`529be5d879cdac0400d0c3a2b497863c2517cf35` after PR #38.
The cause of the two original window losses remains **unknown**. This increment
adds independently tested diagnostics, not an engine or controller repair.
[Issue #39](https://github.com/Rajinder798/ps4-runtime/issues/39) remains open.

## Preserved evidence

All 918 entries in the earlier [artifact manifest](../research/results/2026-10-20-dualsense-controls.json)
were rehashed without changing their bytes. Both failed attempts remain failed.
The original logs, raw Pad files, screenshots and attempted source snapshots stay
under `build/dualsense-extended/axes-001` and `axes-002`.

| Attempt | Qualified stages before failure | Independently rechecked guest records | Original Vulkan PNGs rechecked | Last image sequence / last guest sequence |
| --- | --- | --- | --- | --- |
| axes-001 | 11/17; right-stick-right pending | 1,987; 63,600 bytes | 12 exact images | 1986 / 1986 |
| axes-002 | 9/17; right-stick-left pending | 1,277; 40,880 bytes | 10 exact images | 1271 / 1276 |

The last images match the actual directed guest axes. This later pixel check does
not establish that those phases met the original time/order criteria or that the
test should have continued. The first run's orthogonal SDL value 2441 exceeds
the unchanged ±2048 center bound; that explains a pending capture, not HWND loss.
The second run had announced F12 readiness. No physical button/removal or guest
Pad failure was recorded in either run. Each supervisor reports requested stop,
forced cleanup, verified root exit and an empty process tree. Guest output
continued until that cleanup; process activity does not prove window survival.

`axes-001` recorded focus leaving and returning near the start, roughly 225
seconds before its last guest observation. `axes-002` recorded no focus-state
transition. Polling can miss short transitions. Neither original trace recorded
the HWND, failing thread/PID query, last-error value or lifecycle events, so an
exact failure-time native-window timeline cannot be reconstructed. QPC seconds,
native QPC ticks/frequency, host monotonic time, guest elapsed microseconds and
PNG wall-clock filenames are retained as separate clock domains.

## Source review and competing explanations

| Explanation | Evidence and remaining uncertainty |
| --- | --- |
| HWND destruction or replacement while the engine lives | Consistent with the guard failure, but no original native lifecycle trace. Still unproven. |
| Temporary query failure | The original return values and error were not recorded. A later successful query would not invalidate the first failure. Still possible. |
| Focus loss alone | The observer checks thread/PID before focus. A false foreground/focus flag does not enter the identity-failure branch. Earlier observed focus changes did not fail that guard. |
| Engine exit or crash | Valid late guest records and requested forced cleanup provide no affirmative crash evidence. The process could outlive its window; exact original process state at the failed query is unavailable. |
| Observer marshalling or state defect | HWND and pointer argument types and `GUITHREADINFO` layout were reviewed. No supported causal defect found. Windows host tests cover real queries; they do not prove every original observer interaction correct. |
| F11 fullscreen | Default binding is F11. The inspected shadPS4 handler calls `SDL_SetWindowFullscreen`; the pinned Windows backend changes styles and uses `SetWindowPos` on its current HWND. No destruction call occurs in that path. This is source evidence, not a live F11 reproduction. |
| F12 screenshot | Default capture binding is F12. Its handler queues a Vulkan readback; the save path writes PNG bytes and queues an in-engine notification. No direct native-window destruction call was found there. Both failures follow saved images, which establishes correlation only. |

SDL also contains explicit window destruction/recreation paths elsewhere. No
evidence connects those paths, another thread, an external actor, or a particular
key to either original failure. The owner could not recall F11 versus F12. Do not
label this operator error, an SDL fullscreen bug or a repaired controller defect.
There is no established common cause with audio/input [#33](https://github.com/Rajinder798/ps4-runtime/issues/33)
or disconnected Pad [#37](https://github.com/Rajinder798/ps4-runtime/issues/37).

## Diagnostic improvement

`tests/owned_window_trace.py` keeps the same strict failure decision. It now
records HWND, PID/TID and timestamps, captures last-error immediately on a failed
identity query, and distinguishes a GUI-state-query error. Last-error is null on
a successful query, including a wrong-PID result; a stale error is not evidence.

The analog harness opts into `tests/window_identity_diagnostics.py` only after
the existing supervisor-child, exact engine-path and sole SDL-window checks.
It records:

- A bound snapshot with HWND, observed PID/TID, QPC/Unix timestamp and process
  creation time from a retained query/synchronize-only process handle.
- Process-scoped, out-of-context Windows create/destroy/show/hide/location events
  for `OBJID_WINDOW` / `CHILDID_SELF`, including HWND, event TID, Windows event
  tick, receipt QPC/Unix time and whether the HWND equals the original binding.
- A separately labelled snapshot after failure: `IsWindow`, a second identity
  query, and wait/exit status of the retained process object. Secondary success
  never rescues the failed primary query. Diagnostic failure is also reported.
- A final process/window snapshot, observer shutdown and polling-gap summary,
  including failed sessions. Hooks/handle are released; SDL observer cleanup
  remains in a separate `finally` even if diagnostic shutdown fails.

The callback runs on a dedicated message-loop thread, performs no file I/O and
queues observations for the harness. No code is injected into the engine, and
there is no keyboard/controller hook, global activity log, window rebind, focus
restoration, retry or settings change. A zero/absent process binding is rejected
before hook setup. Other existing consumers keep lifecycle observation disabled.

Windows documents [identity-query failure](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowthreadprocessid),
[process filtering and asynchronous callback delivery](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook),
and the [race and handle-reuse limitations of IsWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-iswindow).
Native events are diagnostic observations, not replacement ownership proofs.
Events before hook registration or after shutdown are outside coverage; absence
of an event is not proof that no lifecycle change occurred. Receipt time is not
event-generation time, and the 32-bit Windows event tick wraps. Separate queries
are not an atomic snapshot. This cannot recover missing historical events or
identify SDL's internal call site. No live engine/Tk performance claim is made.

## Bounded verification and reproduction

No new guest execution, F11/F12 injection, controller action, audio access or
disconnect/reconnect was needed. Three targeted development host executions were
retained alongside two full-suite executions as the diagnostics evolved. The
final host contract uses one hidden ordinary Win32 child per invocation:
unfocused identity succeeds, deliberate destruction fails the unchanged guard
while the process lives, a replacement generates a distinct create event without
rebinding, then process exit is distinguished using the retained handle. This is
host-only diagnostic validation, not reproduction of the shadPS4 anomaly.

```powershell
python tests/window_identity_tests.py -v
python tests/pad_axes_tests.py -v
cmake -S . -B build/native -DCMAKE_BUILD_TYPE=Release
cmake --build build/native --config Release
ctest --test-dir build/native -C Release --output-on-failure
```

For persisted host traces set `PS4_WINDOW_DIAGNOSTIC_TEST_EVIDENCE` to a new,
nonexistent directory before the first command. The test preserves events and
child output on failure as well as success. No hardware is accessed. Portable
tests cover invalid scope, event filtering, wrong PID, secondary-query success
and failure, and GUI-query errors. Linux explicitly skips the native HWND test.

Local results and exact reviewed inputs are in the
[investigation record](../research/results/2026-10-20-window-identity-investigation.json).
Hosted conclusions belong in the PR after final-head logs are reviewed; hosted
tests cannot establish actual physical input or fix the two historical failures.
The earlier 15 button stages, 17 analog stages and 21 guest regressions are
historical PR #38 evidence, not new guest runs for this diagnostic increment.

The investigation stops at this diagnostic improvement. A future recurrence
should preserve the new trace before investigating a specific lifecycle path.

## Physical attempt window-diag-004 (1 November 2026)

The owner approved exactly one new attempt with no automatic retry. Inputs were
the same pinned engine, engine report, `pad_axes` fixture, supervisor and SDL
probe as `window-diag-003`, plus an endpoint observer rebuilt from `main`
`621d5a9`. The controller was the wired, non-virtual Sony `054C:0CE6`. Every
active render endpoint (six) stayed muted in all 2,223 observer samples, and the
observer exited 0 with cleanup confirmed. Full data is in
[the result record](../research/results/2026-11-01-issue39-window-diag-004.json).

**FAILED: 7 of 17 steps.** Step 8 (left-stick-down) was rejected by the
unchanged strict hold rule. While LY was held at 32767, LX reached −2442 and
−2699 for about 0.5 s, beyond the ±2048 sideways bound. The capture cutoff
followed only 1.94 s after the last off-axis sample, with 18 stable samples.
The rule needs 3 s and 20 samples. This is not an engine failure.

**The unexplained window loss was not reproduced.** The first failure (the
capture rejection) was recorded at QPC 154931.679. Eight destroy events and a
hide of the bound window then arrived at 154931.722, all with one Windows event
tick, while the supervisor stopped the engine. Identity queries failed after
that with error 1400. The engine exited 125 under the requested forced cleanup,
and the tree was verified empty. This is consistent with process termination,
not with a window lost before the failure.

**A reporting defect was found and fixed.** The supervisor keeps polling while it
stops the engine. The later identity failure reached `ownership_postmortem`,
which set `result.json`'s top-level `failure`/`error` before the first failure was
consulted. A reader of that field alone would count this run as a new window
loss. `supervision_diagnostics.primary_failure` was correct. The runner now
always prefers the supervisor's recorded first failure, including in the
metadata-failure fallback. New host tests drive the real `supervise()` in the
window-diag-004 order and fail on the previous runner. The attempt itself ran
the previous runner; its raw evidence is unchanged.

Issue #39 stays open. Its original cause is still unknown, and any further
physical attempt needs a new owner approval.
Any deliberate live F11/F12 or controller reproduction requires a separately
agreed bounded session. Original GPL-2.0-or-later test code only; no engine,
fixture, dependency, licensing or redistribution contract changes. Full G4 and
the existing release holds remain open.
