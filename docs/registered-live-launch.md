# Registered live homebrew and preferences

Gate: G3 source-based live launch integration using the existing G4 `live-av`
fixture. Register once, then launch by ID or an ordinary Windows shortcut. A
normal close reports `status: closed`, `completion: live_session_closed`; it
does not claim finite guest completion or independent AV qualification. The
existing registered `interactive-av` remains an automated, bounded self-test.

## Register and launch

Use the existing exact strict engine/report, native helpers and seventh original
fixture from [live AV research](live-av-research.md). No physical controller is
required for the tested keyboard mapping. Focus the SDL window: N is Cross and
B is Circle. Close the window to finish; no input cycles are required.

```powershell
python tools/ps4_launch.py --state-dir build/live-local register --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --live-av build/homebrew/live-av/live_av.oelf --json
python tools/ps4_launch.py --state-dir build/live-local launch live-av --json
python tools/ps4_launch.py --state-dir build/live-local shortcut live-av --directory build/live-shortcuts --helper build/native/ps4-shortcut-helper.exe --json
```

Open `PS4 Runtime - live-av.lnk` using Windows Shell. Successful launches have no
setup prompt, separate library or console. Missing prerequisites or failed
launches still surface through the existing desktop error dialog and local
results. This remains a Python/source-checkout workflow, not an installed engine
bundle. Matching `pythonw.exe`, Windows x86-64 and working engine Vulkan/WASAPI
dependencies are required. Ordinary launches need no capture helper or loopback
preflight. Windows 10 remains unverified.

The shared [session lifetime](live-session.md) supplies bounded startup readiness,
then user-closed lifetime, an inherited launcher-owner handle and Job Object
containment. Launcher death and explicit stop are failures with tree cleanup.
Normal zero exit must leave an independently empty job. Strict audit/output
bounds and the unchanged fixture's 128-observation limit remain enforced.

## Registration and response versions

Explicit registration containing `live-av` writes schema 3. It requires the same
hashed engine, build report, supervisor and reviewed fixture records. Legacy
fixtures may be included. `interactive-av` may also be included, in which case
its hashed capture helper is required. A live-only registration rejects an
unnecessary capture-helper field. Selected live launches never verify or depend
on an unselected self-test capture helper.

Schemas 1 and 2 retain their previous title sets and field requirements; they
never implicitly admit live sessions. Replace registration explicitly with the
complete desired inputs. Failed updates preserve the previous bytes. Every
launch rechecks selected hashes and the pinned source contracts before session
allocation. This is owner-controlled research input validation, not a security
sandbox or a signature against concurrent replacement.

The JSON response remains schema 1, with new status/completion values confined
to the new title. It includes effective settings and sources, readiness, strict
guest-entry observation, normal-exit evidence and tree cleanup. `guest_completed`,
`independent_av_qualification_performed`, graphics/input/Windows-render
qualification and automation flags remain false. Each run has unique session
logs and detailed `session-result.json`; shortcuts retain a desktop response.

## Persistent settings

Only implemented preferences are exposed: diagnostic `debug|info|warning` and
engine volume `0|50|100`. Defaults are Info/Full. The optional Settings window
includes a separate live scope, named volume choices, inheritance and reset.

```powershell
python tools/ps4_launch.py --state-dir build/live-local settings set volume_percent 50 --json
python tools/ps4_launch.py --state-dir build/live-local settings set log_level debug --title live-av --json
python tools/ps4_settings.py --state-dir build/live-local --title live-av
python tools/ps4_launch.py --state-dir build/live-local settings reset --title live-av --key volume_percent --json
```

Resolve defaults, global values and title overrides once before launch. The
snapshot controls the fresh engine configuration, including actual log filter
and volume. Changes apply next launch, through the existing link without
rewriting registration, links, active sessions or earlier evidence. System audio
endpoint and other applications' volume are untouched.

Reading or launching existing schema-1/2 settings does not migrate them. The
first saved non-inherited live title preference upgrades to schema 3, preserving
all previous overrides. Subsequent global/self-test saves or reset never
downgrade it. Global volume in schema 2 already applies to both audio-capable
titles; legacy hello/service scopes remain log-only. Older schema meanings
reject live title entries, and older source rejects new documents instead of
silently dropping preferences. Existing locking, atomic publication and strict
type/key/version/duplicate/size guards remain.

## Acceptance and limits

```powershell
python tests/live_launch_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --fixture build/homebrew/live-av/live_av.oelf --supervisor build/native/ps4-startup-supervisor.exe --capture-helper build/native/ps4-process-audio-capture.exe --helper build/native/ps4-shortcut-helper.exe --output build/live-launch/acceptance-new
```

The opt-in matrix runs nine real guests: two unmodified fresh CLI launches,
four CLI test-host launches and three actual Shell activations using one existing
link. It checks default/global/reopened half, Settings title mute, restored full,
volume-only inheritance/reset, and a no-input shortcut session beyond 125
seconds. It independently checks sequence-bound Vulkan images and guest-written
input records. Four CLI test-host runs additionally verify actual Windows PCM
at full/half/mute and reject wrong gains; mute never claims a tone. The test
host keeps capture a supervisor sibling without modifying its ownership gate.

Shell sessions have independently checked graphics/input/configuration and
normal-close evidence; their PCM is not captured. Production CLI, shortcuts and
ordinary runner send no gameplay keys, screenshots, capture or close requests.
All such automation belongs to the external acceptance driver. The capture
diagnostic requires Windows build 20348+, independently of ordinary launching.
Host-generated signals in unit tests never establish guest behavior.

Local/hosted results remain pending until recorded in this PR. Human usability,
acoustic output, physical controllers, natural guest exit, installed G3, full G4,
commercial gameplay and arbitrary ELF execution remain unverified. Engine,
fixture and dependency pins remain unchanged; the standalone live command is
the fallback. Original additions are GPL-2.0-or-later. No engine, SDK, fixture
binary, captured media, game, firmware or key is distributed. Separate
[source/relink and dependency release holds](release-audit.md) remain open.
