# Saved Cross letter for the live fixture

This source-based G3 increment exposes one existing input capability of the
pinned shadPS4 research engine: the live fixture's Cross letter may be N or G.
It is not arbitrary remapping, physical-controller verification, installed G3
or full G4. Actual guest acceptance is required in addition to host tests.

## Preference and launch contract

`cross_key` accepts exactly lowercase `n` or `g`. It is available globally and
for `live-av`; global values apply only to that title. Defaults use N. The AV
self-test and earlier fixtures have no new control and keep their fixed input
contracts. The optional Settings window displays **Live Cross letter key**,
supports inheritance/reset and applies changes to the next launch. Existing
shortcuts need no regeneration and the normal launcher sends no gameplay input.

```powershell
python tools/ps4_launch.py settings set cross_key g --json
python tools/ps4_launch.py settings set cross_key n --title live-av --json
python tools/ps4_launch.py settings reset --key cross_key --title live-av --json
python tools/ps4_launch.py settings reset --key cross_key --json
```

Inspecting schema 1/2/3 preferences returns default N without rewriting them.
Saving an explicit Cross key upgrades settings to schema 4; subsequent log,
volume and reset operations never downgrade it. Older schemas still reject a
stored `cross_key`. Older launcher versions reject schema 4 rather than
silently ignoring or overwriting the preference. Use the current launcher for
reset; keep a backup before a deliberate application downgrade. Registration
remains schema 3 and existing launch/shortcut metadata is unchanged.

The launcher snapshots effective values before execution. N leaves input-file
generation to the unchanged engine. G stages a fresh `default.ini` from the
reviewed pinned mapping template, replacing only `cross = n` with `cross = g`.
Keypad Cross, gamepad Cross, Circle, sticks, other keyboard bindings and the
engine-generated global hotkeys are preserved. No shared engine profile is
edited or reused. The template hash is checked before engine launch; staged
configuration hashes are recorded. A modified template fails explicitly.
The standalone `run_live_session.py` also accepts `--cross-key n|g`.

## Acceptance and reproduction

The opt-in live-launch driver accepts `--cross-key-matrix` together with
`--muted-endpoint-observer`. It requires Windows to be muted manually before
registration or guest execution and never changes Windows audio settings.
Use the pinned inputs from [muted live launch](muted-live-launch.md), changing
the output to a new directory and adding `--cross-key-matrix`:

```powershell
python tests/live_launch_guest_tests.py `
  --engine build/upstream/windows-x64-strict/shadPS4.exe `
  --engine-report build/upstream/strict-evidence/strict-build.json `
  --fixture build/homebrew/live-av/live_av.oelf `
  --supervisor build/native/ps4-startup-supervisor.exe `
  --capture-helper build/native/ps4-process-audio-capture.exe `
  --helper build/native/ps4-shortcut-helper.exe `
  --muted-endpoint-observer build/native/ps4-endpoint-observer.exe `
  --cross-key-matrix --output build/live-cross-key/mapping-002
```

The nine cases cover default N, global G, reopened G through the same
shortcut, Settings title N, title G plus volume, Settings inheritance, global
reset, an unrelated log edit retaining G and title reset. Each holds/releases
the displaced letter for at least 0.5 seconds without new guest input records,
then requires two real Cross press/release cycles, five independently checked
sequence-bound Vulkan images, exact guest-written pad records and normal close
with an empty owned process tree. Configuration data alone cannot pass.
All unrelated template bindings, effective values, source selection, preference
bytes and the existing shortcut are checked. No PCM is captured or qualified.

Recheck the preceding nine-case muted volume/Settings/125-second launch matrix
and the no-input-close, launcher-death and requested-stop lifetime cases.
The earlier 73-outcome audio/guest campaign remains separate historical
evidence; it is not silently counted as a new run. Host tests cover schema,
scope/type rejection, failed upgrades, snapshotting, UI save/inheritance and
template integrity. Host and hosted source tests do not establish guest input.

Results, pins, raw paths and pending checks are recorded in
[the acceptance result](../research/results/2026-10-20-live-cross-key.json).
The first `mapping-001` attempt found Windows unmuted. The observer rejected it
before registration or guest execution; its stderr and empty report are
preserved. No system audio setting was changed to make the test run.

The subsequent `mapping-002` attempt passed default N, then timed out in the
first G case after guest Cross press/release and three matching Vulkan images.
Owned cleanup succeeded through requested termination. This failed attempt is
retained. The precise missing event is unknown: the test host did not yet record
key-action timing. It is not evidence of an audio failure, and neither a new
mapping defect nor the same cause as the older-baseline input timeout has been
established.

The bounded `mapping-003` diagnostic added a test-only action/observation/image
trace. All nine guest sequences completed, but its trace exposed a separate
test-clock defect: the driver timestamp preceded costly image verification,
shortening a claimed 0.5-second key hold to 0.328 seconds. Those guest runs are
diagnostic evidence and do not qualify the required timing contract. The final
driver starts intervals after verification/action completion and independently
rejects too-short intervals from the recorded trace. A host regression rejects
both that measured short hold and a premature post-image action. This repairs
the test protocol; it does not establish the earlier timeout's root cause.
Final acceptance uses a separate new directory and retains every earlier attempt.

`mapping-004` then rejected a default-N run even though the guest closed
normally with five matching images: the trace contained only three requested
mapped-key actions, with the final guest release preceding any requested key-up.
This is an independent acceptance failure, not a completed transport sequence.
It shows an interruption also occurs in the engine-default N path, which does
not stage the new G profile. Focus was not yet recorded in that attempt, so its
origin remains unlocalized. No automatic key resend or focus restoration was added.

The final `mapping-005` matrix passes all nine scenarios with strict recorded
intervals: six ordinary CLI launches, three Shell activations, 45 independently
checked Vulkan images and two guest Cross cycles per launch. Its read-only
endpoint report contains 3,234 samples over 101,332 ms, maximum gap 48 ms,
with mute, scalar volume 1 and the default endpoint unchanged. Read-only focus
changes are now logged for future recurrences; the test never changes focus.
Passing repeats do not establish that the earlier input interruption is fixed.
Owner acceptance of the documented unresolved input risk remains necessary.

All nine prior muted launch/volume/Settings cases also pass, including the
125-second no-input shortcut. The three additional lifetime outcomes pass:
normal no-input close, launcher-death containment and requested-stop cleanup.
These give 21 final expected guest outcomes and 85 independently checked Vulkan
images, separate from excluded/diagnostic attempts. All 20 local Windows host
suites pass. Hosted results remain separate and are updated in the PR after
completed current-head logs are reviewed.
All observed endpoint samples remain muted with unchanged volume/device. The
prior-volume matrix's largest polling gap is 1,078 ms, larger than the requested
25 ms interval; the mapping matrix's maximum is 48 ms. Observation cannot exclude
changes between samples. This gap is retained as a measurement limit, not hidden
by another run or treated as proof of uninterrupted endpoint state.

## Provenance, fallback and limits

`config/live-input-default.ini` retains the default mapping data from
`GetDefaultInputConfig` in
[pinned input_handler.cpp](https://github.com/shadps4-emu/shadPS4/blob/e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5/src/input/input_handler.cpp),
with its shadPS4 copyright and GPL-2.0-or-later notice. The root LICENSE supplies
the license text. This is source-derived configuration data, not an imported or
linked engine implementation. The only non-comment change at runtime is the
reviewed Cross letter. Original adapter/test additions use GPL-2.0-or-later.
No engine, fixture, SDK, game, firmware, key or captured binary is distributed.

N/default or a single-key reset is the functional fallback. There are no engine,
fixture, dependency or audio-threshold changes. Acoustic output, alternate
keyboard layouts/focus behavior, Windows 10, physical controllers and broader
input mappings remain unverified. The unresolved PCM spike and older-baseline
input timeout remain in [issue #33](https://github.com/Rajinder798/ps4-runtime/issues/33);
this work does not diagnose or fix them. Existing
[dependency/source/relink release holds](release-audit.md) remain open.

## Cleanup verification hardening

The first PR Windows workflow failed the existing owner-death host test: after
reading a successful cleanup report, reopening the root PID still returned an
unsignaled process. The push Windows job and both Linux jobs passed; that does
not erase the failed PR job. Its complete log is preserved locally as
`build/live-cross-key/ci-39361426345.log`.

The supervisor previously checked only empty Job Object accounting before
reporting cleanup. It now also requires its retained root-process handle to
signal exit within the same existing five-second cleanup budget. The additive
`root_exit_verified` report field records that condition. The owner-death test
opens and retains the exact root/descendant handles before killing the launcher,
then still requires immediate signaled state at report time. It adds no wait
allowance to the assertion and avoids reopening potentially reused PIDs.
Twenty bounded host repetitions pass with those retained handles.

These changes close a supported verification gap; the original CI job did not
retain the old process object, so accounting/exit ordering versus PID reuse
cannot be distinguished from its log. No claim is made that a confirmed process
leak was reproduced locally. Fresh guest regressions using the rebuilt helper
are recorded separately in
[the cleanup supplement](../research/results/2026-10-20-live-cross-key-cleanup.json).
Earlier input/endpoint observations remain in the original result unchanged.
The rebuilt helper passes all 21 scoped guest outcomes again: nine strict N/G,
nine prior launch/volume cases and three lifetime cases. Every resulting
transport reports `root_exit_verified: true`. All 20 local host suites pass;
final current-head Windows/Linux CI and completed-log review remain required.

This is a helper binary change, not an engine or fixture change. Its new hash
is recorded. Existing research registrations correctly reject a replaced helper
until their inputs are explicitly refreshed through registration; do not bypass
hash checks. Use `register --replace` with the same state directory and all
intended fixture arguments, because replacement is a complete registration.
The stable shortcut target need not change after that refresh.
Installer upgrade/migration guarantees remain outside this source-based gate.
