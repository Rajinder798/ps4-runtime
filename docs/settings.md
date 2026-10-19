# Persistent settings for supported capabilities

Gate: G3 settings-core and optional-window increments. The local launch interface persists a
global preference and per-title overrides for a capability the pinned engine
already implements: diagnostic log level. The subsequent
[AV volume increment](av-volume-settings.md) adds the verified Mute/Half/Full
choices for the audio-capable self-test. An optional Windows Settings window
edits that same store. Other settings categories and installer lifecycle remain future work. This
source/Python workflow still uses the separate research engine and does not
clear its redistribution holds.

The [registered live scope](registered-live-launch.md) adds the same log/volume
controls for `live-av`. An explicit saved live override uses schema 3, preserves
earlier preferences and never rewrites registration or existing shortcuts.

## Supported preference and commands

The [AV self-test launch profile](av-self-test-launch.md) adds `interactive-av`
as a diagnostic-settings scope in the CLI/window. Its effective `log_level`
reaches the actual AV engine session. Its subsequent volume preference uses
schema 2 only after an explicit audio save; schema-1 diagnostics remain supported.

`log_level` accepts `debug`, `info` or `warning`. Default is `info`. It controls
the engine's per-session diagnostic log after its logging configuration is
loaded. Debug includes more detail; Warning retains warnings/errors while
excluding Info/Debug records. Bootstrap diagnostics, structured strict audit,
Vulkan host capture and required guest behavior checks are retained independently.
Log level does not change graphics quality, performance, audio or input.

```powershell
python tools/ps4_launch.py --state-dir build/launch/local settings show --json
python tools/ps4_launch.py --state-dir build/launch/local settings set log_level warning --json
python tools/ps4_launch.py --state-dir build/launch/local settings set log_level debug --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings show --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --title hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --json
python tools/ps4_launch.py --state-dir build/launch/local settings reset --all --json
```

Use the same state directory as registration/shortcuts. As before, omitting
`--state-dir` uses `PS4_RUNTIME_HOME` or the platform default. Settings commands
work without launching an engine or requiring registration, and support the
three reviewed launch IDs. No unsupported controls or telemetry opt-in are exposed.
This preference layer adds no upload/telemetry operation; logs remain local.

The resolution order is **defaults → global → per-title override**. `show`
returns stored settings, defaults, effective values, their sources (`default`,
`global`, `title`) and `takes_effect: next_launch`. Without a title, it shows
global effective values. Reset with a title removes that title's overrides and
inherits global values. Reset without a title clears global overrides while
preserving title overrides. `--all` clears both. Reset does not delete logs,
registration, shortcuts, inputs or session data.

## Optional Windows Settings window

Open this separately when you want to change preferences. It is never opened by
normal guest launches and does not require engine registration. Use Windows Python
3.12+ with working Tcl/Tk (included in a standard Windows Python installation when
that component is selected). The launch CLI itself does not import or require Tk.

```powershell
pythonw tools/ps4_settings.pyw --state-dir build/launch/local
pythonw tools/ps4_settings.pyw --state-dir build/launch/local --title hello-world
```

Use the same state directory as your registered shortcuts. Omitting `--state-dir`
uses the existing `PS4_RUNTIME_HOME`/platform default. A configured Windows `.pyw`
association can also open `tools/ps4_settings.pyw` with that default state; this
PR installs no association or Start-menu entry. `python tools/ps4_settings.py`
opens the same window with a console, useful during development. Missing/broken
Tk displays a prerequisite error in the console-free entry and exits 4.

Choose **All supported titles**, **Hello world**, **Service roundtrip** or
**Graphics, input and audio self-test**. The
window shows the saved effective level and whether it comes from the default,
global preference or title override. Choose Debug, Info or Warning and **Save**.
**Use default (Info)** removes that log-level global override; **Inherit global preference**
removes that preference's title override while preserving other preferences.
**Reset this scope** clears all supported overrides in the selected scope;
**Reset all scopes** clears global and all title overrides. These actions affect
only preferences. Changes apply to the next launch, including an existing shortcut.
Switching scope, Refresh or closing the window discards unsaved edits. Refresh
also picks up external CLI/other-window changes; updates always re-read and
validate current disk contents under the existing writer lock.

The folder shown at the bottom is selectable/copyable. Validation, busy-writer
and save errors appear inline. Invalid/future formats disable updates until the
underlying file is deliberately repaired or moved aside and Refresh succeeds;
neither Save nor Reset silently recovers/overwrites them. The implemented audio
choice and its capability-scoped behavior are described in
[persistent AV volume](av-volume-settings.md). There are no placeholder
graphics/performance/input/device/latency or telemetry controls, and no guest-launch button.

## Persistence and launch behavior

`settings.json` schema 1 is separate from `launch-config.json` registration:

```json
{
  "schema_version": 1,
  "global": {"log_level": "warning"},
  "titles": {"hello-world": {"log_level": "debug"}}
}
```

The initial format had no prior schema to migrate. The audio follow-up preserves
it and explicitly upgrades on volume save as documented above. Missing files use defaults
without creating a file or prompt. Unknown/future versions, fields, titles,
invalid types/levels, duplicate keys, malformed/oversized JSON fail closed.
They are not silently discarded, downgraded or overwritten, including by reset.
Future supported migrations must be explicit and tested before accepting a new
format. To recover a damaged/unsupported file, preserve a copy and repair it or
move it aside deliberately; the runtime never performs that recovery silently.

Updates hold a nonblocking OS file lock, read the latest valid document, and
publish a fully written temporary file with atomic replacement. Concurrent
writers receive `settings_busy`; closing the handle or terminating the writer
releases the lock. `.settings.lock` is a persistent lock file, not a stale
ownership marker. Failed validation/save preserves the published preferences.
Readers see a complete old or new document. Storage failures use
`settings_write_failed` (exit 6); invalid settings and contention use exit 3.
Invalid CLI values/usage retain exit 2. JSON/text behavior matches the existing
launch interface.

Each launch takes one validated effective-settings snapshot before allocating
a session. Both launch responses and retained session results record effective
values and their sources. Corrupt preferences reject execution before an engine
starts. Changing settings affects the next launch and does not modify an active
session. Existing shortcuts read the current settings on every activation,
without recreation or extra prompts.

The launcher supplies the effective log level to the shared strict runner,
which writes only the supported `Log.filter` value (`*:debug`, `*:info` or
`*:warning`) in that session's fresh `user/config.json`. It also fixes
`Log.flush_level` to `trace` so accepted diagnostics are flushed before bounded
termination. This is an internal evidence-retention measure, not a user knob.
The engine merges this group over its defaults and saves its normal complete
config. The standalone research runner keeps its existing default behavior
when no preference is supplied. No pinned engine source/patch/header is changed.

## Reproduction and evidence

CTest `settings-contract` has 13 policy/CLI tests for precedence, reset,
persistence across processes, future/invalid format preservation, failed writes,
real OS writer contention/release, immutable launch snapshots and pre-execution
rejection, explicit volume migration, type/capability validation and independent
key updates. These are host tests, not PS4 guest execution.

```powershell
python tests/settings_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --helper build/native/ps4-shortcut-helper.exe --output build/settings/acceptance-001
```

Choose a new output. This runs six real guest sessions across default, global,
per-title override and reset cases, using both direct CLI launches and existing
Windows shortcuts. It checks the engine's retained filter, actual session-log
levels, strict guest messages/timing, independent service output and tree cleanup.
Warning records must remain, so a broken filter that disables all logging cannot
pass. Registration and shortcut command properties must remain unchanged.
A future-version settings file is then rejected before execution and preserved
by a rejected reset. The filtered [local evidence record](../research/results/2026-10-18-settings.json)
contains measured log-level counts and input/source identifiers, not performance
benchmarks. Complete logs/configs/audits remain in the local acceptance output.
Hosted checks are recorded separately in the PR.

For the optional-window acceptance, run the same command above with
`--settings-ui --output build/settings-ui/acceptance-001` instead of the original
`--output`. This reopens a real Tk window for each preference change, invokes its
actual controls, then independently checks the same six guest outcomes and three
existing shortcut activations. The [window evidence record](../research/results/2026-10-18-settings-ui.json)
records this separate run. `settings-ui-contract` additionally checks visible
saved values, inheritance/reset, errors, failed-write preservation, recovery and
Tk initialization failure and volume controls using real Windows widgets (eight tests including help).
These automated control tests do not establish manual accessibility/usability
certification or Linux graphical support.

No graphics/performance/input controls, commercial compatibility or release
readiness is established; the later volume control has its own scoped evidence.
New source is original GPL-2.0-or-later. The window
uses Tcl/Tk supplied by the user's Python; no Python/Tk runtime is bundled here,
and any future packaged runtime needs its own license/notice review. No engine,
SDK/homebrew/game binaries, firmware or keys are committed or uploaded. The
[existing dependency/source/relink holds](release-audit.md) remain open.
