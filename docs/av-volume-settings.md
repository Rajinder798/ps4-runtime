# Persistent volume for the registered AV self-test

Gate: G3 preferences backed by the G4 volume capability. The registered
`interactive-av` self-test now reads a saved global or per-title volume on
every CLI or existing Windows shortcut launch. The optional Settings window
edits the same store; normal launches never open it. This remains source-based
research using the separately pinned shadPS4 engine, not an installed product.

## Capability and acceptance

Only the three [independently verified research levels](audio-volume-research.md)
are exposed: **Mute (0%), Half (50%), Full (100%)**. Full is the default. No
continuous slider, device, latency or live-adjustment control is added. Volume
is applicable globally to the AV self-test and as an `interactive-av` override.
Hello/service scopes have no volume control, reject explicit volume overrides,
and retain their log-only effective settings even with a global audio preference.

Acceptance requires persisted defaults/global/title/inheritance/reset values to
change actual captured Windows-rendered guest PCM at the requested amplitude,
with strict entry, zero unresolved imports, three independently checked Vulkan
images, guest Cross press/release, normal engine close and helper cleanup. A
saved value or configuration field alone cannot grant success. Existing Shell
links and registration must remain byte-identical. Invalid saved preferences
must fail before session allocation or engine launch.

The dependency is the merged Windows small-buffer repair and existing volume
oracle/capture/launch contracts. Engine, fixture, supervisor and capture helper
pins do not change. A missing Windows capture prerequisite is a failed launch,
never a silent disk-only fallback. Mute deliberately verifies requested silence;
it cannot establish a tone source, so `audio_muted: true` and
`audio_tone_verified: false` are explicit in its launch response.

## Commands and Settings

```powershell
python tools/ps4_launch.py --state-dir build/launch/local settings set volume_percent 50 --json
python tools/ps4_launch.py --state-dir build/launch/local settings set volume_percent 0 --title interactive-av --json
python tools/ps4_launch.py --state-dir build/launch/local settings show --title interactive-av --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --key volume_percent --title interactive-av --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --key volume_percent --json
pythonw tools/ps4_settings.pyw --state-dir build/launch/local --title interactive-av
```

Use the same state directory as registration and shortcuts. The CLI accepts
only exact `0`, `50`, `100` volume strings, and rejects unsupported scopes before
writing state. JSON values must be exact integers, not booleans, floats or strings.
`settings show` reports each applicable effective value and its independent source
(`default`, `global`, `title`). Legacy scopes omit the volume field.

The window provides the three named choices plus default/inherit. Audio is
disabled for legacy scopes with an explanatory label. Save atomically updates
only changed keys, so changing log level cannot erase a volume override and
choosing volume inheritance cannot erase diagnostic preferences. Reopening or
Refresh reloads saved values. Changes affect the next launch only; Windows
endpoint/other-application volume is never changed.

`reset --key` removes one override. Existing scope reset (including the UI button)
clears both supported preferences in that scope; reset-all clears every override.
Neither operation touches registration, links, logs or active sessions.

## Versioned persistence

Schema 1 log-only documents remain valid. Reading them, launching or editing only
diagnostics does not migrate them. The first explicit non-inherited volume save
upgrades to schema 2 under the existing writer lock, preserving all diagnostics:

```json
{
  "schema_version": 2,
  "global": {"log_level": "info", "volume_percent": 50},
  "titles": {"interactive-av": {"log_level": "debug", "volume_percent": 0}}
}
```

Schema 1 still rejects audio keys. Schema 2 accepts audio only in the global/AV
scopes. Reset never downgrades a schema-2 document. Older source rejects version
2 rather than dropping preferences. Future versions, unknown keys/titles,
duplicate keys, malformed/oversized JSON and invalid types/levels fail closed,
including reset. Failed migration/write preserves the previous published bytes.
Atomic replacement, OS writer locks and immutable per-launch snapshots remain.

## Reproduction and validation

```powershell
python tests/av_volume_settings_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --helper build/native/ps4-shortcut-helper.exe --fixture build/homebrew/interactive-av/interactive_av.oelf --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --output build/av-volume-settings/acceptance-new
```

Choose a new directory. The nine real launches include seven AV sessions and
two legacy sessions: schema-1 default, global half twice through fresh CLI
processes, UI title mute through an existing Shell link, restored title full,
UI inheritance through that same link, global-volume-only reset, then both
legacy fixtures with global audio saved. Each actual AV capture must reject
the wrong requested gain. The matrix verifies preserved diagnostics, unchanged
registration/link bytes, prior session evidence and invalid-volume rejection
before any new session. It uses actual UI controls and process-filtered capture,
not generated PCM as guest evidence.

The 17 local host suites pass. The settings suite has 13 tests, Settings UI has
eight (including help), and the existing launch suite also requires verified
volume on AV success. Final UI controls/layout checks also pass separately.

The [filtered result](../research/results/2026-10-19-av-volume-settings.json)
records **52 expected actual guest outcomes passed**: nine new registered-volume
launches, nine prior registered launches, six legacy Settings/UI launches and
28 earlier Windows/disk/volume outcomes. This includes the unchanged 256-frame
audio-only fixture. Nine actual Shell activations use existing links. Every
requested volume passes its original amplitude/mute oracle and rejects a wrong
gain; mute's tone qualification remains explicitly false. Post-run PCM/audit/
image/config/window-response hashes were cross-checked, and engine logs add no
warning/error patterns relative to the ordinary-window PR #27 matrix.

Raw outputs remain in `build/av-volume-settings/{acceptance-001,
registered-regressions-001,legacy-settings-regressions-001,audio-regressions-001}`.
The Windows/Linux host workflows pass at implementation commit `089598d`; final
evidence-commit statuses and inspected log links are reported separately in the
PR. The engine/fixture/patch/header inputs exactly match the reviewed PR #27
strict-engine, homebrew and dependency evidence. No new engine source rebuild
is claimed for this preferences-only change.

## Limits and licensing

No acoustic speaker/headphone output, physical controller, commercial gameplay,
complete G4, installed G3, general game support or standalone engine claim. The
AV capture API retains its Windows build 20348+ requirement; Windows 11 build
26220 is the local test host. Other formats/levels and 256-frame hardware playback
remain unverified. The existing minimized-window exception diagnostics remain
documented in the [audio repair](small-buffer-audio.md); this adds no minimization
support. There is no engine/source/fixture or dependency modification.

Original additions use GPL-2.0-or-later. No engine/SDK/fixture/game/audio binary,
firmware or key is committed or uploaded. No telemetry or microphone capture is
added. Python/Tk are supplied by the user; no runtime is bundled. Source/relink/
runtime/resource [release holds](release-audit.md) still block redistribution.
