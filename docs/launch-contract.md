# Local supported-homebrew launch contract

Gate: G3 prerequisite. The source command `tools/ps4_launch.py` adds one-time
local registration and repeatable launches by supported fixture ID. It delegates
to the same pinned shadPS4 research process and strict observation harness.
It requires Python 3.12+ and this source checkout; it is not an installed native
application or a distributable engine bundle. [Local Windows shortcuts](shortcuts.md)
now invoke this contract. G3 installer/upgrade/uninstall, optional Settings UI
and persistent game profiles remain unfinished.

## Register once, launch by name

Build the [strict engine and hello_world](startup-research.md#build-and-run) and
the [second fixture](homebrew-services.md#reproduction), then register existing
local files. Registration verifies the engine/build report against the current
research contract and checks each fixture's reviewed hash. It does not execute
guest code, download anything or modify an upstream checkout.

```powershell
python tools/ps4_launch.py --state-dir build/launch/local register --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --json
python tools/ps4_launch.py --state-dir build/launch/local launch hello-world --json
python tools/ps4_launch.py --state-dir build/launch/local launch service-roundtrip --json
```

Visual Studio native builds place the supervisor under `Release/`. Register at
least one of the two fixtures; only `hello-world` and `service-roundtrip` are
recognized IDs. `--state-dir` precedes the command. It can be omitted to use
`PS4_RUNTIME_HOME`, or `%LOCALAPPDATA%/PS4Runtime` on Windows when that environment
override is absent. Routine launches then need only the fixture ID. These two
fixtures terminate by deliberate bounded observation; they are not interactive
games with a normal game exit lifecycle.

`launch-config.json` schema 1 stores absolute file paths and SHA-256 values for
the engine, engine report, supervisor and selected fixtures. A complete temporary
file is atomically published; first registration refuses an existing file.
Use `register --replace` with the complete desired registration to update it
explicitly after a verified rebuild/move. A failed replacement preserves the
previous configuration. The state filesystem must support local hard links for
first publication and atomic replacement. Unsupported schemas, unknown fields,
duplicate keys, relative paths and malformed hashes fail; newer schemas are not
silently downgraded. This registration describes local runtime inputs, not
graphics/audio/input preferences or a settings implementation.

Before every launch, the command checks the selected registered files again,
including the supervisor/build-report hashes and current pinned research
source/header/fixture contract. Changed or missing inputs fail before process
start; an unselected fixture's absent file does not prevent another fixture's
launch. The local config and build report are trusted owner-controlled inputs,
not signatures or a security sandbox. File hashing does not remove the existing
native guest trust model or races against concurrent file replacement.

## Response, errors and evidence

With `--json`, each completed command emits exactly one schema-1 JSON object to
stdout. Operation failures also use JSON and leave stderr empty. CLI usage
errors retain argparse's stderr/exit-2 behavior. Without `--json`, success is a
short stdout message; failures use `error[code]: message` on stderr and include
the session log location when available. The original C++ inspector/probe
commands and their stdout/stderr/JSON/exit contracts are unchanged.

Launch responses include `operation`, `title`, `status`, `session_id`,
`logs_directory`, `engine_launch_attempted`, `guest_entry_observed`,
`guest_execution_tested`, `tree_cleanup` and
`upstream_redistribution_approved: false`. Errors add `error.code` and
`error.message`. Success has `status: completed` and
`completion: fixture_observed_and_stopped`: strict guest evidence, fixture
behavior/output checks and confirmed cleanup passed. It does not mean natural
guest exit or commercial playability.

| Exit | Meaning | Representative error codes |
| --- | --- | --- |
| 0 | Registration or bounded supported-fixture launch completed | — |
| 2 | Invalid CLI usage | argparse stderr |
| 3 | Registration/configuration/title selection failed | `not_registered`, `invalid_config`, `unsupported_title`, `already_registered`, `registration_failed` |
| 4 | Input verification, host or prerequisite failed | `input_verification_failed`, `unsupported_host`, `prerequisite_failed` |
| 5 | Attempted guest launch failed its observation/cleanup contract | `guest_failed` |
| 6 | Session allocation, evidence processing or result storage failed | `session_failed` |

Valid launch requests automatically allocate `sessions/<UUID>/` and never reuse
an existing session. Rejected preflight requests have null session/log fields
and do not create sessions. Each allocated session retains `launch-result.json`,
the original detailed `startup-result.json`, Vulkan diagnostics and fresh
`session/` logs/audit trace/user directory. The service fixture also retains its
random input and guest output. Configuration and older session evidence are not
rewritten by launching. Logs are local, retained until manually removed, and
may contain machine paths; no automatic upload or telemetry is implemented.

## Acceptance and limits

Portable CTest `launch-contract` exercises real CLI JSON/text/usage errors,
configuration persistence/validation, failed update preservation, exact-input
rechecks, unique sessions, collision refusal and distinct failure statuses.
Policy tests substitute the engine execution callback and are not guest evidence.
Existing Windows process lifetime tests continue to exercise the real supervisor.

The opt-in acceptance command uses the real launcher in separate processes,
registers once and launches each real fixture twice. It requires actual guest
entry/behavior and cleanup, different session IDs, unchanged configuration and
retained earlier evidence, then rejects an unsupported ID and a changed copy of
the fixture before execution. Original SDK/fixture inputs are not modified:

```powershell
python tests/launch_guest_tests.py --engine build/upstream/windows-x64-strict/shadPS4.exe --engine-report build/upstream/strict-evidence/strict-build.json --supervisor build/native/ps4-startup-supervisor.exe --hello-world build/homebrew/hello-world/hello_world.oelf --service-roundtrip build/homebrew/service-roundtrip/service_roundtrip.oelf --output build/launch/acceptance-001
```

Use a new output directory. Results are in its `summary.json`; individual session
directories contain the complete evidence. The filtered
[local validation record](../research/results/2026-10-18-launch-contract.json)
contains reproducibility identifiers and outcomes. Hosted results are reported
separately in the PR; ordinary hosted policy builds do not execute a PS4 guest.

The 30-second observation budget and strict checks are preserved; no new fake
settings controls are exposed. Persistent saves/per-title preferences,
interactive graphics/input/audio, engine Unicode-path qualification, installer
lifecycle and game compatibility remain separate work. The new source
uses GPL-2.0-or-later with no new third-party library. No engine/SDK/game binaries,
firmware or keys are committed or uploaded. The existing
[release audit holds](release-audit.md#remaining-release-holds-and-next-implementation)
still block engine redistribution; local research launches do not clear them.
