# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Check the static engine import-coverage tool against an original synthetic source tree."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import engine_coverage
from make_sce_imports import make_sce_imports, name_to_nid

exe = sys.argv[1]


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def rejects(action, text, label):
    try:
        action()
    except ValueError as error:
        check(text in str(error), f"{label}: {error}")
        return
    raise AssertionError(f"{label}: accepted")


USLEEP, PRINTF, GUARD, PROC = (name_to_nid(n) for n in
                               ("sceKernelUsleep", "printf", "__stack_chk_guard", "sceKernelGetProcParam"))
# Original miniature engine layout: one registration file, the macro header and a name table.
LIBRARY = f'''void RegisterLib(Core::Loader::SymbolsResolver* sym) {{
    LIB_FUNCTION("{USLEEP}", "libkernel", 9, "libkernel", sceKernelUsleep);
    LIB_FUNCTION("{PRINTF}", "libc", 1,
                 "libSceLibcInternal", printf);
    LIB_OBJ("{GUARD}", "libSceLibcInternal", 1, "libc", &guard);
    LIB_FUNCTION("{USLEEP}", "libkernel", 1, "libkernel", sceKernelUsleep);
}}
'''
MACROS = '''#define LIB_FUNCTION(nid, lib, libversion, mod, function) LinkSymbolImpl(sym, nid, lib)
#define LIB_OBJ(nid, lib, libversion, mod, obj) LinkSymbolImpl(sym, nid, lib)
'''
NAMES = f'STUB("{USLEEP}", sceKernelUsleep)\nSTUB("{PROC}", sceKernelGetProcParam)\n'

with tempfile.TemporaryDirectory(prefix="engine-coverage-", dir=Path(exe).resolve().parent) as directory:
    root = Path(directory)
    source = root / "engine"
    for relative, text in (("src/core/libraries/kernel.cpp", LIBRARY), ("src/core/libraries/libs.h", MACROS),
                           ("src/core/aerolib/aerolib.inl", NAMES)):
        (source / relative).parent.mkdir(parents=True, exist_ok=True)
        (source / relative).write_text(text, encoding="utf-8")
    fixture = root / "fixture.elf"
    fixture.write_bytes(make_sce_imports()[0])
    imports = root / "imports.json"
    imports.write_text(subprocess.run([exe, "imports", fixture, "--json"], capture_output=True, text=True,
                                      check=True, timeout=10).stdout, encoding="utf-8")
    inventory = json.loads(imports.read_text(encoding="utf-8"))

    found = engine_coverage.registrations(source)
    check(len(found) == 3 and sum(len(s) for s in found.values()) == 4, "duplicate registrations collapse by key")
    check(found[(USLEEP, "libkernel", "libkernel")][0]["site"] == "src/core/libraries/kernel.cpp:2",
          "registration site")
    check(found[(GUARD, "libSceLibcInternal", "libc")][0]["kind"] == "obj", "LIB_OBJ kind")
    check((PRINTF, "libc", "libSceLibcInternal") in found, "multi-line registration")
    report = engine_coverage.coverage(inventory, found, engine_coverage.nid_names(source))
    check(report["imports"] == 4 and report["registered_imports"] == 2 and report["missing_count"] == 2, "counts")
    # printf is registered under a different library/module pair, so it does not match; version is ignored.
    check([(m["nid"], m["name"], m["library"], m["module"]) for m in report["missing"]] ==
          [(PRINTF, None, "libc", "libc"), (PROC, "sceKernelGetProcParam", "libkernel", "libkernel")],
          "missing imports by NID, library and module")
    check(report["static_prediction_only"] is True and report["execution_performed"] is False, "capability flags")

    cli = [sys.executable, "-B", str(TOOLS / "engine_coverage.py"), "report", "--source", str(source),
           "--imports", str(imports)]
    text = subprocess.run(cli, capture_output=True, text=True, timeout=30)
    check(text.returncode == 0 and "2 of 4 imports have an HLE registration" in text.stdout, text.stderr)
    check(f"missing {PROC} sceKernelGetProcParam libkernel libkernel function" in text.stdout, "text entry")
    check(json.loads(subprocess.run(cli + ["--json"], capture_output=True, text=True, timeout=30).stdout) == report,
          "CLI JSON equals library result")

    (source / "src/core/libraries/kernel.cpp").write_text(LIBRARY + '    LIB_FUNCTION(nid_variable, "x", 1, "x", f);\n')
    rejects(lambda: engine_coverage.registrations(source), "registration macros but", "unparsed registration")
    empty = root / "empty"
    (empty / "src").mkdir(parents=True)
    rejects(lambda: engine_coverage.registrations(empty), "No LIB_FUNCTION", "tree without registrations")
    rejects(lambda: engine_coverage.coverage({"operation": "relocations", "schema_version": 1}, found, {}),
            "imports --json", "wrong input document")
    rejects(lambda: engine_coverage.prepare(source, True), "not empty", "existing destination")
    failed = subprocess.run(cli[:5] + [str(empty), "--imports", str(imports)], capture_output=True, text=True, timeout=30)
    check(failed.returncode == 1 and "engine coverage error:" in failed.stderr, "CLI error exit")
print("Engine import coverage checks passed")
