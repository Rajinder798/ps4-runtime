# Licensing and third-party boundaries

## Project license

Copyright (C) 2026 Rajinder Singh.

On 17 October 2026 the owner selected **GNU GPL version 2 or, at your option,
any later version** (`GPL-2.0-or-later`) for PS4 Runtime's original code, tests,
scripts, build files, configuration and documentation, unless a file explicitly
states otherwise. The complete, unmodified GPL version 2 text is in
[LICENSE](../LICENSE); the "or later" permission is granted here, in the
[README](../README.md#license) and in source-file SPDX notices. The Free Software
Foundation's copyright in the license text is separate from the project's
copyright. The software is provided without warranty as described in LICENSE.

This completes the repository license decision in the G1 foundation work. It
does not complete the component audit required before G2 runtime integration.

## Contributions and distribution

- Submit original contributions under GPL-2.0-or-later and only contribute work
  you have the right to license. Preserve existing author and license notices;
  use the actual contributor's name for new copyright notices.
- Retain LICENSE and applicable copyright/license notices with redistributed
  source. When distributing modified files, include prominent change notices
  and dates as required by GPL version 2 section 2(a).
- Before distributing a covered binary, satisfy the corresponding-source
  requirements of the chosen GPL version. For GPL version 2, section 3(a)
  permits accompanying it with complete corresponding machine-readable source,
  including the scripts used to control compilation and installation. A link to
  the latest branch alone is not a release source-compliance plan.
- Donations, sponsorship and selling copies or support are allowed; payment
  does not remove recipients' GPL rights or the distributor's obligations.
  The project license itself requires no purchase or registration.

Use the full license terms for distribution decisions. The
[GNU application guide](https://www.gnu.org/licenses/gpl-howto.en.html) and
[GNU FAQ](https://www.gnu.org/licenses/gpl-faq.en.html) provide further guidance.

## External material is not relicensed

No shadPS4 or God of War III implementation is currently imported or linked into
the runtime. The runtime targets use the C++ standard library; research
downloads and outputs live under ignored build directories. The project grant
does not apply to those downloads or transfer any third-party copyright.

| Material | Current relationship | Licensing boundary |
| --- | --- | --- |
| shadPS4 at `e6c79a5fe0ea2f3d03fcb9c5c50cf61af063f3f5` | Separate reference checkout/build | Inspected core files declare GPL-2.0-or-later; dependencies retain their own terms. Preserve upstream authors and notices if reused. |
| OpenOrbis at `b458dfd9d2f5c40aa249b127c9b9b4488afdc686` | Separate SDK/sample build for startup research | Root license is GPL v3; individual samples, tools and libraries require their own review. Building the fixture does not license it under this project's grant. |
| God of War III PC reference | Architectural comparison only | Its inspected README declares GPL v2 or later with separate third-party licenses. No implementation is imported. |
| Compiler, C++ runtime, CMake, Python and CI actions | External build/test tools and runtime support | Keep their own licenses. Review applicable runtime redistribution terms and exceptions before shipping binaries; the project license does not replace them. |

The pinned source links, build inputs and evidence are recorded in the
[foundation decision](decisions/0001-foundation.md),
[upstream baseline](upstream-baseline.md) and
[lock file](../config/upstream-lock.json).

## Required review before integration or binary releases

Record exact components and revisions, their actual licenses, required
attributions, source obligations, link/bundle boundaries and compatibility with
the selected GPL version. Preserve upstream notices rather than replacing them
with this project's author header. GPL-2.0-or-later permits choosing a later GPL
version where appropriate; it does not make every dependency compatible.

The automated shadPS4 inventory only discovers candidate root notice files and
hashes. It is not a completed license review. In particular,
`externals/mesa-kosmickrisp/externals/mesa` had no matching root notice filename
and needs manual investigation. The full component audit and release-specific
notice/source bundle remain open. No upstream binaries, SDK, sample binary,
game, firmware or proprietary material are added by this licensing change.
