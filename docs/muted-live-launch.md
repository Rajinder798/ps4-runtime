# Muted Windows live-launch acceptance

This is a source-based G3 acceptance increment on merged PR #32, not completion
of installed G3 or full G4. Ordinary CLI and existing shortcut launches must
honor saved application volume independently of Windows endpoint mute. The
engine and settings schema are unchanged. A status-publication sharing fix was
required by an observed failure during this acceptance campaign.

## Contract and test boundary

The opt-in registered live matrix accepts `--muted-endpoint-observer` and runs
the same nine settings/launch scenarios without process-loopback capture. Four
previously PCM-qualified test-host launches become ordinary CLI launches. Six
unmodified CLI launches and three actual Shell activations check defaults,
global Half, reopened preferences, Settings UI title Mute, title Full,
inheritance, reset and a 125-second no-input shortcut session. Independent
guest pad records and sequence-bound Vulkan screenshots remain required in the
eight interactive cases. All nine require guest entry, effective engine
configuration, normal close and an independently empty process tree. Invalid
settings and a modified owned fixture must still fail before guest execution.

`ps4-endpoint-observer` is built only with Windows `BUILD_TESTING`. Before any
registration or guest launch it requires an already-muted active default render
endpoint. It repeatedly reads the default eRender/eConsole device identity,
mute and master volume scalar using Windows COM. It never creates an audio
stream, calls an endpoint setter, restores settings or changes a device.
Observation continues through settings changes, launches and cleanup. A device,
mute or volume change, observer death, read failure or bounded timeout fails the
matrix. The test requests cleanup of its owned guest on failure; it cannot undo
an external unmute or guarantee silence after another application changes mute.

Polling requests a 25 ms interval; actual maximum gaps are reported. Changes
between reads are not excluded. Device identifiers are compared inside the
helper and are not written into the report. Windows volume scalar is observed,
never treated as an application-gain measurement. In particular, endpoint mute
does not rewrite saved application Mute/Half/Full values.

The helper's fresh JSONL report, ready signal, stop request and stderr are kept
in the new output directory. Overall success is withheld until the helper exits
normally and the full report validates. No automatic retries or audio changes
are performed. Hosted tests cover report rejection and native argument guards;
they do not need an audio endpoint or establish guest execution.

## Reproduction

Keep Windows muted manually before starting. Do not alter audio settings during
the matrix. Build the host targets with testing enabled, then run:

```powershell
python tests/live_launch_guest_tests.py `
  --engine build/upstream/windows-x64-strict/shadPS4.exe `
  --engine-report build/upstream/strict-evidence/strict-build.json `
  --fixture build/homebrew/live-av/live_av.oelf `
  --supervisor build/native/ps4-startup-supervisor.exe `
  --capture-helper build/native/ps4-process-audio-capture.exe `
  --helper build/native/ps4-shortcut-helper.exe `
  --muted-endpoint-observer build/native/ps4-endpoint-observer.exe `
  --output build/muted-live-launch/matrix-001
```

Choose an unused output directory. The capture-helper argument remains part of
the shared driver's existing interface; this mode never invokes it. Ordinary
production launches do not depend on the observer or loopback capture.

## Evidence and limits

Results and source/input hashes are recorded in
[the acceptance result](../research/results/2026-10-20-muted-live-launch.json).
Raw local reports, logs and screenshots remain under ignored `build/` paths.
On the local Windows build, all nine post-change registered scenarios and the
three additional lifetime outcomes passed. The registered matrix recorded 6,497
endpoint samples over 203,620 ms; the maximum observed sampling gap was 52 ms.
All samples retained mute, volume scalar 1 and the same default endpoint. The
Settings UI and all three existing-shortcut launches passed without regenerating
the shortcut or rewriting preferences during launch. Forty independently
checked Vulkan images cover the eight interactive registered cases. No PCM was
captured in this campaign. All 20 Windows host suites passed; hosted results
are reported separately in the PR after completion and log review.
This muted matrix provides no PCM amplitude, acoustic output or audio-spike
qualification. It does not replace the earlier 73-outcome PR #32 guest campaign
or establish that its unresolved intermittent observation is absent or fixed.
The doubled-amplitude recording and separate older-baseline input timeout
remain tracked in [issue #33](https://github.com/Rajinder798/ps4-runtime/issues/33)
and the [audio investigation](audio-spike-investigation.md).

No engine, fixture, dependency pin, PCM threshold or schema is changed. The
ordinary session status publisher now uses Windows `ReplaceFileW` for existing
snapshots, with compatible delete-sharing readers in both live guest drivers.
The local supervisor may be relinked from identical source; binary
hashes are recorded per campaign. No engine rebuild is claimed. Windows 10,
physical controllers, human usability, natural guest exit, installer delivery
and commercial gameplay remain unverified. Original test additions use
GPL-2.0-or-later; no third-party source or binary is added. Separate
[dependency/source/relink release holds](release-audit.md) remain open.

## Observed status-file failure and focused repair

The first muted attempt passed three CLI scenarios, then failed during the
Settings title-Mute Shell scenario. Its retained session result reports
`WinError 5` replacing `session-status.tmp` with `session-status.json`, after
guest entry and sequences 0..3. Cleanup was forced with an empty final tree;
this is a failed launch, not normal close. Endpoint observation passed throughout.

File-only Windows regression tests reproduce denial of the old `Path.replace`
operation while a destination reader is open, including a delete-sharing
reader. `ReplaceFileW` with a compatible reader succeeds while the old reader
continues to see its prior snapshot. Its documented sharing mode is
[read/write/delete](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew).
The new publisher preserves the status schema, fresh temporary-file publication
and first-publication path, uses no ignored-error flags and propagates failures.
There are no publication retries, test retries or truncated in-place writes.
This establishes a supported sharing mechanism consistent with the observed
failure; the exact competing handle in that original attempt was not traced.
An incompatible external reader can still prevent publication and fail a
session; arbitrary third-party locks are not repaired or hidden.

The failed output remains at `build/muted-live-launch/matrix-001`, separate from
the post-change matrix. The lifetime driver's opt-in muted mode additionally
checks no-input close, launcher death and requested stop, with endpoint
observation. It rejects the PCM-capture long case in muted mode; the nine-case
matrix already covers a 125-second ordinary shortcut session without capture.
