"""Check the actual CLI contract, JSON types, deterministic probe, and error exits."""
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from make_probe import make_probe

exe = sys.argv[1]


def run(*args):
    return subprocess.run([exe, *map(str, args)], capture_output=True, text=True, check=False, timeout=10)


def check(condition, label):
    if not condition:
        raise AssertionError(label)


with tempfile.TemporaryDirectory(prefix="cli-test-", dir=Path(exe).resolve().parent) as directory:
    probe = Path(directory) / "probe with spaces \u03bb.elf"
    payload = make_probe()
    check(hashlib.sha256(payload).hexdigest() == "a7ae081593a449bd9c77d4efcb6e800aed2c499ec4b9cc6bebf379ebed46d7e7", "fixture hash changed")
    probe.write_bytes(payload)
    result = run("inspect", probe, "--json")
    check(result.returncode == 0 and not result.stderr, result.stderr)
    report = json.loads(result.stdout)
    check(report["type"] == "ET_SCE_DYNEXEC" and report["os_abi"] == 9, "SCE metadata")
    check(report["entry"] == 4096 and report["entry_in_executable_segment"] is True, "entry")
    check(report["execution_supported"] is False, "inspection capability")
    check(len(report["segments"]) == 2 and report["segments"][1]["memory_size"] == 4096, "segments")
    check(run("inspect", probe).stdout.endswith("general PS4 process execution is not implemented.\n"), "text status")
    result = run("probe", probe, "--json")
    check(result.returncode == 0 and not result.stderr, result.stderr)
    mapped = json.loads(result.stdout)
    check(mapped["operation"] == "probe" and mapped["return_value"] == 42, "native return value")
    check(mapped["mapped_segments"] == 2 and mapped["mapped_bytes"] == 0x4000, "mapping report")
    check(mapped["copied_bytes_verified"] == 14 and mapped["zero_fill_bytes_verified"] == 4088, "copy/BSS verification")
    check(mapped["protections_applied"] is True and mapped["general_execution_supported"] is False, "limited execution")
    check("Synthetic probe returned: 42" in run("probe", probe).stdout, "probe text result")
    for offset, width, value, code in [
        (0x1000, 1, 0xCC, "unsupported_probe"),
        (0x1001, 1, 43, "unsupported_probe"),
        (24, 8, 0x1001, "unsupported_probe"),
        (68, 4, 7, "writable_executable_segment"),
        (120, 4, 2, "unsupported_mapping_segment"),
        (136, 8, 0x1000, "overlapping_segment_pages"),
        (160, 8, 64 * 1024 * 1024, "image_too_large"),
    ]:
        changed = bytearray(payload)
        struct.pack_into({1: "<B", 4: "<I", 8: "<Q"}[width], changed, offset, value)
        probe.write_bytes(changed)
        result = run("probe", probe, "--json")
        check(result.returncode == 1 and not result.stdout and f"error[{code}]" in result.stderr, code)
    probe.write_bytes(payload)
    check(run("--help").returncode == 0 and run("--version").returncode == 0, "help/version")
    for args in [(), ("run", probe), ("inspect",), ("inspect", probe, "--bogus")]:
        check(run(*args).returncode == 2, f"usage exit: {args}")
    missing = run("inspect", Path(directory) / "missing.elf", "--json")
    check(missing.returncode == 1 and not missing.stdout and "error[open_failed]" in missing.stderr, "open error")
    probe.write_bytes(bytes.fromhex("4f153d1d"))
    bad = run("inspect", probe, "--json")
    check(bad.returncode == 1 and not bad.stdout and "error[unsupported_self]" in bad.stderr, "SELF rejection")
    probe.write_bytes(payload[:100])
    bad = run("inspect", probe)
    check(bad.returncode == 1 and "error[segment_table_out_of_bounds]" in bad.stderr, "truncated table")
print("CLI contract and deterministic probe checks passed")
