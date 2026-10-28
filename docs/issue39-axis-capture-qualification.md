# Issue #39: offline Stage 6 capture qualification

Gate: G4 host-side diagnostic prerequisite. This change makes the guide's
capture acceptance use the existing final acceptance rule before advancing.
It does not physically qualify revised code or resolve earlier HWND losses.
The dependency is unmerged PR #47 at
`992ed612cbf69f5d6d6c4b58fccb5ccd4bcfb832`; main remains
`9b3810e38718637ac6bc89661f13391832c10776`. This is a separate stacked Draft PR.
Neither PR #46 nor #47 is changed or merged.

## Preserved observation

The owner completed all 17 screenshot steps in `window-diag-003` and closed the
engine using X when prompted. All 17 PNGs match exact guest records and every
Vulkan pixel. The engine exited 0, without forced termination, with an empty
owned tree and independently confirmed helper cleanup. The later host verifier
rejected index 5 (human Stage 6, left-stick-up); the original overall FAIL and
16/17 final sustained checks remain unchanged. This was not a normal-close
failure or a reproduced unexpected HWND identity loss. The earlier
`window-diag-002` operator-reported early-F12 failure and forced-exit
classification also remain unchanged.

The offline investigation verified all original sealed hashes, sizes and
modification times: 48 physical files plus the 31-file review/prelaunch seal
for `window-diag-003`, and the 42-file physical / 30-file review/prelaunch seals
for `window-diag-002`. A wider inventory protects 8,407 historical files.
All raw evidence stays local and unchanged; no binary or private host inventory
is committed. `preflight-005/process-raw.json` remains invalid historical
evidence: expected original SHA-256
`c5ca48a0fbb509a6ffa3cc72bad61ea6e8a7481503b08fcfd6957fd3edb2302e`,
preserved overwritten SHA-256
`00d7528d03f6ca452e1b171dca2fddcb03d3dfbeff15c87f56e8d80c3b9d75eb`.
The original bytes are unavailable and its original manifest is unchanged;
that file supplies no valid historical safety evidence.

## Exact reconstruction and clock limits

SDL counter frequency is 10,000,000 ticks/s. The table's QPC seconds are SDL
integer counters divided by that frequency or Python perf_counter values.
Guest audit elapsed time and guest Pad timestamp are separate domains.
Python monotonic values in progress rows are not silently treated as QPC.

| Observation | Recorded timestamp or interval | Meaning |
| --- | --- | --- |
| Stage 6 instruction | QPC 85114.3843059; progress monotonic 85111.968 | Guest lower audit boundary 52.489143 s |
| SDL stable start | QPC 85120.1959570 | Start of the matching suffix |
| Readiness SDL prefix end | QPC 85123.2502007 | 30 records, 3.0542437 s |
| F12 readiness log | monotonic 85120.875 | Guide emits ready_for_human_f12; no physical keypress timestamp |
| Readiness guest suffix | audit 57.389825–61.823258 s, sequences 468–506 | 39 records, 4.433433 s |
| Online capture-check SDL prefix end | QPC 85125.1382504 | 48 records, 4.9422934 s; uniquely reconstructs the stored duration |
| Matching neighboring SDL rows | QPC 85125.2425821 / .3479890 / .4531485 / .5584565 | LX 1413 / 1413 / 1670 / 1670, LY -32768 |
| First later off-axis row | QPC 85125.6639514 | LX 2184, LY -32768, RX 385, RY 0; LX exceeds 2048 |
| Recorded capture cutoff | QPC 85125.7320741 | Host time after completed-PNG decoding and pixel checks; not F12 time |
| Next SDL row | QPC 85125.7694270 | LX 1927, LY -32768; after the frozen cutoff |
| Next instruction | QPC 85125.7330792 | Guide advances to center in the original online path |
| Capture guest suffix | audit 57.389825–63.806145 s, sequences 468–523 | 56 records, 6.416320 s; guest sample 523 axes [128,0,128,128] |

Both earlier SDL prefix boundaries are derived by applying the actual suffix
function to all prefixes and finding the unique recorded duration, not by
inventing a snapshot-acquisition timestamp. The source reads the SDL file at
the start of a poll, computes readiness, then discovers/decodes/verifies the
PNG before assigning capture_qpc_seconds. The physical F12 action, screenshot
request QPC, exact SDL acquisition QPC and exact screenshot-completion QPC were
not recorded. They cannot be reconstructed exactly. Native screenshot naming
uses system wall time when the renderer constructs output paths, not a key-event
audit. The filename is 18:41:16.191 IST; filesystem creation / last-write times
are 18:41:16.1921793 / 18:41:16.2000891 IST. These are separate file observations,
not precise keypress or render-completion timestamps.

Final validation selects all axis_state rows whose QPC is **less than or equal
to** 85125.7320741. Its last eligible row is the off-axis sample 68.1227 ms
before that cutoff. The suffix immediately ends: zero records, zero seconds.
The matching row 37.3529 ms after cutoff cannot repair that suffix.

## Proven cause and unchanged policy

Causes A/B/C are established together: online and final use different effective
SDL cutoffs; additional serialized rows become eligible between snapshot and
capture bookkeeping; file read / PNG processing / capture timestamp assignment
are non-atomic. Cause D is excluded for this example: stable_suffix correctly
rejects the later off-axis row. Strict policy E applies (hold the straight
position until advance) and is already stated in the guide, but does not excuse
the online/final mismatch or establish operator intent. No operator blame or
physical fault diagnosis follows from these records.

The correction keeps the final policy, including ±2048 non-target SDL axes,
±28672 target threshold, guest bounds, at least three seconds / 20 observations,
maximum 0.35-second gaps, exact image identity and physical directional events.
It does not move the cutoff back to F12 readiness or exempt later drift.

After verifying a completed PNG, the runner freezes the same post-image capture
QPC used previously and retains that one capture as pending. It keeps pumping
all existing safety/liveness/deadline checks. It awaits an ordered SDL axis
sample at or after the frozen cutoff. The single native writer timestamps and
flushes samples in order, so that later sample establishes publication of the
whole earlier prefix. Non-monotonic axis snapshots fail. No new screenshot,
input, observation process or session is requested and the cutoff never moves.

The same extracted `verify_capture` function is then used both before guide
advance and by final `verify_phases`. A late off-axis row therefore fails
before image_verified/advance. An all-stable capture passes. Rows strictly
after the frozen cutoff have no effect, exactly as in the old final rule.
The existing 540-second overall limit, observer lifetimes and cleanup path
remain; a missing watermark cannot grant acceptance or extend those budgets.
`capture_waiting_for_sdl` records the frozen candidate in host diagnostics.
Earlier readiness is permission to request F12, not irrevocable phase success.

Moving the cutoff to the old snapshot, accepting any earlier good window,
loosening the tolerance or inferring a physical F12 timestamp would require a
separate policy decision; none is implemented here.

## Host validation and review limits

Before any correction, a separate script against the unchanged PR #47 sources
reproduced live readiness / 4.9422934-second online stability followed by the
zero-length final suffix; it also replayed the sealed full run and confirmed
its original final rejection and normal engine exit 0. Both checks pass as
reproductions of a failure, not as physical qualification.

`tests/pad_axes_capture_tests.py` contains 11 deterministic methods: measured
neighbor timing, stable acceptance, inclusive cutoff / immediately-after-cutoff,
late drift, delayed capture/publication, strict 2048/2049/2184 boundaries,
invalid guest/hold/motion, ordering, and two fully stubbed calls through the
actual production poll closure. The latter prove no advance before coverage,
late-invalid rejection and stable acceptance using the original fixed cutoff.
No native process, Tk window or device is created by those stubbed calls.
The existing eight axes evidence methods remain required. The new suite is
registered in normal Windows/Linux CTest; full exact-head CI results belong in
the Draft PR and local final report, not inferred from proposed workflows.

Reproduce host-only checks:

```powershell
python -B tests/pad_axes_capture_tests.py
python -B tests/pad_axes_tests.py
cmake -S . -B build/host-new -DCMAKE_BUILD_TYPE=Release
cmake --build build/host-new --config Release
ctest --test-dir build/host-new -C Release --output-on-failure
```

Use a fresh build path. Never invoke the opt-in physical runner for this task.
The original source/tests/docs are GPL-2.0-or-later, with no external dependency,
engine/fixture distribution, proprietary SDK, firmware, game, key or relink
approval added. Existing redistribution holds remain.

GO for independent host-source review only after exact-head host checks pass.
NO-GO for physical/release/G4 acceptance: no new physical authorization exists
and the corrected behavior has not been physically tested. Keep Issues #33,
#37 and #39 open, recovery FAIL 6/9, connected PnP FAILED, Windows integration
NO-GO and G5 frozen. No merge or speculative engine fix is authorized.

## Follow-up independent blockers

The independent final review of head `1d5bfa55` found stale cutoff-edge coverage,
malformed witness and inherited postmortem-error masking blockers. See the
[versioned host correction](issue39-axis-qualification-v2.md). The original
physical FAIL and this initial implementation record remain historical.
