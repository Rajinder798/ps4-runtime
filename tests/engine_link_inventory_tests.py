# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable checks of the engine link inventory with a synthetic PE, map and checkout."""
import copy
import fnmatch
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import engine_link_inventory as inv


def make_pe(imports=(), delayed=(), magic=0x20B):
    """Minimal PE32+ with one section holding import/delay-import descriptors and names."""
    base, raw = 0x1000, 0x200
    imports_size, delayed_size = 20 * (len(imports) + 1), 32 * (len(delayed) + 1)
    names, content = bytearray(), bytearray(imports_size + delayed_size)
    def name_rva(text):
        offset = imports_size + delayed_size + len(names)
        names.extend(text.encode("ascii") + b"\0")
        return base + offset
    for i, dll in enumerate(imports):
        struct.pack_into("<I", content, 20 * i + 12, name_rva(dll))
    for i, dll in enumerate(delayed):
        struct.pack_into("<I", content, imports_size + 32 * i + 4, name_rva(dll))
    content += names
    header = bytearray(raw)
    header[:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x40)
    header[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", header, 0x44, 0x8664, 1, 0, 0, 0, 240, 0x22)
    optional = 0x58
    struct.pack_into("<H", header, optional, magic)
    struct.pack_into("<I", header, optional + 108, 16)
    if imports:
        struct.pack_into("<II", header, optional + 112 + 8, base, imports_size)
    if delayed:
        struct.pack_into("<II", header, optional + 112 + 8 * 13, base + imports_size, delayed_size)
    section = optional + 240
    header[section:section + 8] = b".idata\0\0"
    struct.pack_into("<IIII", header, section + 8, len(content), base, len(content), raw)
    return bytes(header) + bytes(content)


MAP = """ shadps4

  Address         Publics by Value              Rva+Base               Lib:Object

 0000:00000000       .absolut                   0000000000000000     <absolute>
 0001:00000010       main                       0000700000001010 f   main.cpp.obj
 0001:00000020       helper                     0000700000001020 f i main.cpp.obj
 0001:00000030       SDL_Init                   0000700000001030 f   SDL3-static:SDL.c.obj
 0001:00000040       absl_a                     0000700000001040     absl_base:a.obj
 0001:00000050       absl_b                     0000700000001050     absl_strings:b.obj
 0002:00000060       __imp_CreateFileW          0000700000002060     kernel32:KERNEL32.dll

 entry point at         0001:00000010

 Static symbols

 0001:00000070       local                      0000700000001070 f   main.cpp.obj
"""


class EngineLinkInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)
        for path, text in (("externals/sdl3/LICENSE.txt", "zlib terms"), ("externals/abseil-cpp/LICENSE", "apache"),
                           ("src/font.ttf", "font bytes")):
            (self.source / path).parent.mkdir(parents=True, exist_ok=True)
            (self.source / path).write_text(text)
        (self.source / "REUSE.toml").write_text('version = 1\n[[annotations]]\npath = ["src/font.ttf"]\n'
                                                'SPDX-License-Identifier = "OFL-1.1"\n')
        sha = lambda p: hashlib.sha256((self.source / p).read_bytes()).hexdigest()
        self.config = {
            "schema_version": 1, "upstream_revision": "0" * 40,
            "flags": {"gpl3-selection": "Apache-2.0 needs GPL-3.0"},
            "allowed_dlls": {"windows-system": ["api-ms-win-*.dll", "kernel32.dll"], "msvc-runtime": ["vcruntime140.dll"]},
            "components": {
                "sdl3": dict(kind="upstream-static", libraries=["SDL3-static"], notice="externals/sdl3/LICENSE.txt",
                             notice_sha256=sha("externals/sdl3/LICENSE.txt"), license="Zlib", flags=[], extra_notices=[]),
                "abseil-cpp": dict(kind="upstream-static", libraries=["absl_*"], notice="externals/abseil-cpp/LICENSE",
                                   notice_sha256=sha("externals/abseil-cpp/LICENSE"), license="Apache-2.0",
                                   flags=["gpl3-selection"], extra_notices=[]),
                "windows-sdk": dict(kind="system", libraries=["kernel32"], notice=None, notice_sha256=None,
                                    license="LicenseRef-Windows-SDK", flags=[], extra_notices=[]),
            },
            "assets": [dict(path="src/font.ttf", sha256=sha("src/font.ttf"), declared_license="OFL-1.1")],
        }
        self.libraries, self.own = inv.map_contributions(MAP)

    def run_inventory(self, config=None, libraries=None, dlls=("KERNEL32.dll", "VCRUNTIME140.dll"), delayed=()):
        return inv.inventory(libraries=libraries or self.libraries, own_symbols=self.own, dlls=list(dlls),
                             delayed=list(delayed), config=config or self.config, source=self.source)

    def test_map_contributions(self):
        self.assertEqual(self.libraries, {"SDL3-static": 1, "absl_base": 1, "absl_strings": 1, "kernel32": 1})
        self.assertEqual(self.own, 3)
        for text in ("no symbol table", MAP.replace("SDL3-static:SDL.c.obj", "x.obj").replace("absl_base:a.obj", "a.obj")
                     .replace("absl_strings:b.obj", "b.obj").replace("kernel32:KERNEL32.dll", "k.obj")):
            with self.assertRaises(ValueError):
                inv.map_contributions(text)

    def test_pe_imports(self):
        self.assertEqual(inv.pe_imports(make_pe(["KERNEL32.dll", "USER32.dll"], ["dbghelp.dll"])),
                         (["KERNEL32.dll", "USER32.dll"], ["dbghelp.dll"]))
        self.assertEqual(inv.pe_imports(make_pe()), ([], []))
        for blob in (b"ELF", make_pe(["a.dll"], magic=0x10B), b"MZ" + b"\0" * 62):
            with self.assertRaises((ValueError, struct.error)):
                inv.pe_imports(blob)

    def test_passing_inventory_records_obligations(self):
        report = self.run_inventory()
        self.assertEqual((report["status"], report["errors"]), ("passed", []))
        self.assertEqual(report["components"]["abseil-cpp"]["libraries"], {"absl_base": 1, "absl_strings": 1})
        self.assertEqual(report["obligations"]["gpl3-selection"]["components"], ["abseil-cpp"])
        self.assertEqual(report["dll_imports"], {"windows-system": ["kernel32.dll"], "msvc-runtime": ["vcruntime140.dll"]})
        self.assertEqual(report["third_party_dlls_imported"], [])
        self.assertFalse(report["upstream_redistribution_approved"])

    def assert_fails(self, fragment, **kwargs):
        report = self.run_inventory(**kwargs)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(any(fragment in error for error in report["errors"]), report["errors"])

    def test_unmapped_library_fails(self):
        self.assert_fails("libfoo matches 0", libraries={**self.libraries, "libfoo": 3})

    def test_library_in_two_components_fails(self):
        config = copy.deepcopy(self.config)
        config["components"]["sdl3"]["libraries"].append("absl_base")
        self.assert_fails("absl_base matches 2", config=config)

    def test_stale_component_fails(self):
        libraries = {k: v for k, v in self.libraries.items() if k != "SDL3-static"}
        self.assert_fails("sdl3 is not linked", libraries=libraries)

    def test_changed_or_missing_notice_fails(self):
        (self.source / "externals/sdl3/LICENSE.txt").write_text("other terms")
        self.assert_fails("Notice changed for sdl3")
        (self.source / "externals/sdl3/LICENSE.txt").unlink()
        self.assert_fails("Notice missing for sdl3")

    def test_component_without_notice_fails(self):
        config = copy.deepcopy(self.config)
        config["components"]["sdl3"].update(notice=None, notice_sha256=None)
        self.assert_fails("sdl3 has no notice", config=config)

    def test_asset_change_or_license_mismatch_fails(self):
        config = copy.deepcopy(self.config)
        config["assets"][0]["declared_license"] = "MIT"
        self.assert_fails("does not declare MIT", config=config)
        (self.source / "src/font.ttf").write_text("changed")
        self.assert_fails("asset missing or changed")

    def test_unexpected_dll_fails_including_delay_loaded(self):
        self.assert_fails("Unexpected DLL import: openal32.dll", dlls=("KERNEL32.dll", "OpenAL32.dll"))
        report = self.run_inventory(delayed=("SDL3.dll",))
        self.assertIn("Unexpected DLL import: sdl3.dll", report["errors"])
        self.assertEqual(report["delay_loaded"], ["sdl3.dll"])

    def fetched_setup(self):
        build = self.source.parent / (self.source.name + "-build")
        (build / "_deps/sdl-src").mkdir(parents=True)
        (build / "_deps/sdl-src/LICENSE").write_text("fetched zlib terms")
        (self.source / "cmake").mkdir()
        url, archive = "https://example.invalid/sdl-1.0.tar.gz", "ab" * 32
        (self.source / "cmake/fetch.cmake").write_text(f"FetchContent_Declare(sdl URL {url} URL_HASH SHA256={archive.upper()})\n")
        config = copy.deepcopy(self.config)
        config["flags"]["build-time-download"] = "fetched"
        config["components"]["sdl3"].update(
            kind="fetched-static", notice="build:_deps/sdl-src/LICENSE", flags=["build-time-download"],
            notice_sha256=hashlib.sha256((build / "_deps/sdl-src/LICENSE").read_bytes()).hexdigest(),
            fetch=dict(url=url, sha256=archive, declared_by="cmake/fetch.cmake",
                       declared_by_sha256=hashlib.sha256((self.source / "cmake/fetch.cmake").read_bytes()).hexdigest()))
        return build, config

    def test_fetched_dependency_uses_build_notice_and_pinned_declaration(self):
        build, config = self.fetched_setup()
        report = inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=["KERNEL32.dll"], delayed=[],
                               config=config, source=self.source, build=build)
        self.assertEqual((report["status"], report["errors"]), ("passed", []))
        self.assertEqual(report["components"]["sdl3"]["fetch"]["declared_by"], "cmake/fetch.cmake")
        self.assertEqual(report["obligations"]["build-time-download"]["components"], ["sdl3"])
        without_build = inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=[], delayed=[],
                                      config=config, source=self.source)
        self.assertTrue(any("build directory" in e for e in without_build["errors"]), without_build["errors"])

    def test_fetched_dependency_declaration_must_match(self):
        build, config = self.fetched_setup()
        for change in ("url", "sha256"):
            broken = copy.deepcopy(config)
            broken["components"]["sdl3"]["fetch"][change] = "https://other.invalid/x.tar.gz" if change == "url" else "cd" * 32
            report = inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=[], delayed=[],
                                   config=broken, source=self.source, build=build)
            self.assertTrue(any("does not name the recorded URL and hash" in e for e in report["errors"]), change)
        (self.source / "cmake/fetch.cmake").write_text("changed")
        report = inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=[], delayed=[],
                               config=config, source=self.source, build=build)
        self.assertTrue(any("Download declaration missing or changed" in e for e in report["errors"]))
        (build / "_deps/sdl-src/LICENSE").write_text("other")
        report = inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=[], delayed=[],
                               config=config, source=self.source, build=build)
        self.assertTrue(any("Notice changed for sdl3" in e for e in report["errors"]))

    def closure_setup(self):
        """A header-only component, a generated file and a deps log for two engine objects and one library object."""
        build = self.source.parent / (self.source.name + "-build")
        for path, text in (("externals/json/LICENSE.MIT", "mit"), ("externals/json/json.hpp", "// SPDX-License-Identifier: MIT\n"),
                           ("externals/vk/LICENSE.md", "apache"), ("externals/vk/vulkan_core.h", "/* SPDX-License-Identifier: Apache-2.0 */\n"),
                           ("externals/sdl3/SDL.h", "plain"), ("src/main.cpp", "int main() {}")):
            (self.source / path).parent.mkdir(parents=True, exist_ok=True)
            (self.source / path).write_text(text)
        (build / "gen/fonts").mkdir(parents=True)
        (build / "gen/fonts/font.g.cpp").write_text("data")
        (build / "_deps/x").mkdir(parents=True)
        (build / "_deps/x/x.h").write_text("x")
        sha = lambda p: hashlib.sha256((self.source / p).read_bytes()).hexdigest()
        config = copy.deepcopy(self.config)
        config["components"]["sdl3"]["sources"] = ["externals/sdl3"]
        config["components"]["json"] = dict(kind="header-only", libraries=[], sources=["externals/json"], notice="externals/json/LICENSE.MIT",
                                            notice_sha256=sha("externals/json/LICENSE.MIT"), license="MIT", flags=[],
                                            extra_notices=[], file_spdx=["MIT"])
        config["components"]["vk"] = dict(kind="header-only", libraries=[], sources=["externals/vk"], notice="externals/vk/LICENSE.md",
                                          notice_sha256=sha("externals/vk/LICENSE.md"), license="Apache-2.0", flags=["gpl3-selection"],
                                          extra_notices=[], file_spdx=["Apache-2.0"])
        config["closure"] = dict(engine_object_marker="CMakeFiles/shadps4.dir/", toolchain_markers=["/Windows Kits/"],
                                 engine_sources=["src"], generated={"gen/fonts": "engine", "_deps/x": "sdl3"})
        s, b = str(self.source).replace("\\", "/"), str(build).replace("\\", "/")
        deps = (f"CMakeFiles/shadps4.dir/src/main.cpp.obj: #deps 6, deps mtime 1 (VALID)\n    {s}/src/main.cpp\n"
                f"    {s}/externals/json/json.hpp\n    {s}/externals/vk/vulkan_core.h\n    C:/Program Files (x86)/Windows Kits/10/include/x.h\n"
                f"    {b}/gen/fonts/font.g.cpp\n    {b}/_deps/x/x.h\n\n"
                f"CMakeFiles/shadps4.dir/src/other.cpp.obj: #deps 1, deps mtime 1 (VALID)\n    {s}/externals/sdl3/SDL.h\n\n"
                f"externals/zlib/CMakeFiles/z.dir/z.c.obj: #deps 1, deps mtime 1 (VALID)\n    C:/elsewhere/not-checked.h\n")
        return build, config, deps

    def run_closure(self, build, config, deps):
        return inv.inventory(libraries=self.libraries, own_symbols=self.own, dlls=["KERNEL32.dll"], delayed=[],
                             config=config, source=self.source, build=build, deps=deps)

    def test_source_closure_classifies_engine_objects(self):
        build, config, deps = self.closure_setup()
        report = self.run_closure(build, config, deps)
        self.assertEqual((report["status"], report["errors"]), ("passed", []))
        closure = report["source_closure"]
        self.assertEqual((closure["engine_objects"], closure["files"], closure["engine_files"], closure["toolchain_files"]), (2, 7, 2, 1))
        self.assertEqual(closure["header_only"], ["json", "vk"])
        self.assertEqual(closure["components"]["vk"]["file_spdx"], {"Apache-2.0": 1})
        self.assertEqual(closure["components"]["sdl3"]["files"], 2)
        self.assertEqual(report["obligations"]["gpl3-selection"]["components"], ["abseil-cpp", "vk"])
        # Without the dependency log the header-only components are not reported at all.
        plain = self.run_inventory(config=config)
        self.assertNotIn("json", plain["components"])
        self.assertIsNone(plain["source_closure"])

    def test_source_closure_fails_closed(self):
        build, config, deps = self.closure_setup()
        s = str(self.source).replace("\\", "/")
        cases = {
            "belongs to no reviewed component": deps.replace("externals/json/json.hpp", "externals/unknown/u.h"),
            "Unclassified compiled file": deps.replace("C:/Program Files (x86)/Windows Kits/10/include/x.h", "D:/random/x.h"),
            "json is not compiled into the engine": deps.replace(f"    {s}/externals/json/json.hpp\n", ""),
        }
        for fragment, text in cases.items():
            if fragment == "belongs to no reviewed component":
                (self.source / "externals/unknown").mkdir(exist_ok=True)
                (self.source / "externals/unknown/u.h").write_text("u")
            report = self.run_closure(build, config, text)
            self.assertTrue(any(fragment in e for e in report["errors"]), (fragment, report["errors"]))
        (self.source / "externals/vk/vulkan_core.h").write_text("// SPDX-License-Identifier: GPL-3.0-only\n")
        report = self.run_closure(build, config, deps)
        self.assertTrue(any("declares GPL-3.0-only, not reviewed for vk" in e for e in report["errors"]), report["errors"])
        broken = copy.deepcopy(config)
        broken["closure"]["generated"]["_deps/x"] = "missing-component"
        report = self.run_closure(build, broken, deps)
        self.assertTrue(any("names an unknown component" in e for e in report["errors"]), report["errors"])
        for text in ("not a deps line\n", "externals/z.obj: #deps 1, deps mtime 1 (VALID)\n    x.h\n"):
            with self.assertRaises(ValueError):
                inv.parse_deps(text, "CMakeFiles/shadps4.dir/")

    def test_undefined_flag_fails(self):
        config = copy.deepcopy(self.config)
        config["components"]["sdl3"]["flags"] = ["made-up"]
        self.assert_fails("undefined flags", config=config)

    def test_committed_table_is_consistent_with_the_recorded_run(self):
        config = json.loads(inv.CONFIG.read_text(encoding="utf-8"))
        record = json.loads((ROOT / "research/results/2026-11-15-engine-link-inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "passed")
        self.assertEqual(record["config_sha256"], inv.digest(inv.CONFIG))
        linked = [lib for c in record["components"].values() for lib in c["libraries"]]
        self.assertEqual(len(linked), record["library_count"])
        for library in linked:
            owners = [cid for cid, c in config["components"].items()
                      if any(fnmatch.fnmatchcase(library, p) for p in c["libraries"])]
            self.assertEqual(len(owners), 1, library)
        for cid, component in config["components"].items():
            self.assertTrue(set(component["flags"]) <= set(config["flags"]), cid)
            self.assertIn(component["kind"], ("upstream-static", "prebuilt-static", "fetched-static", "header-only", "toolchain", "system"))
            if component["kind"] in ("upstream-static", "prebuilt-static", "fetched-static", "header-only"):
                self.assertRegex(component["notice_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(record["third_party_dlls_imported"], [])
        closure = record["source_closure"]
        self.assertEqual(closure["header_only"], sorted(cid for cid, c in config["components"].items() if c["kind"] == "header-only"))
        for cid, entry in closure["components"].items():
            reviewed = set(config["components"][cid].get("file_spdx", [])) | {"none"}
            self.assertTrue(set(entry["file_spdx"]) <= reviewed, cid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
