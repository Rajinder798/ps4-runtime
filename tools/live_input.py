# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
"""Narrow live-fixture keyboard adapter for the pinned engine's existing parser."""
import hashlib
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "config/live-input-default.ini"
TEMPLATE_SHA256 = "1234585343611edc8c22136f6477971f48cf02a0fda629a7acb938907dbd62b6"


def stage_input(work, key):
    if key not in ("n", "g"):
        raise ValueError("Only live Cross letter N or G is supported")
    if key == "n":
        # Keep the engine's unchanged default generation for all old launches.
        return dict(cross_key="n", source="engine_default")
    data = TEMPLATE.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != TEMPLATE_SHA256:
        raise ValueError("Pinned live input template changed")
    if data.count(b"\ncross = n\n") != 1:
        raise ValueError("Live input template has an ambiguous Cross letter")
    data = data.replace(b"\ncross = n\n", b"\ncross = g\n")
    directory = work / "user/input_config"
    directory.mkdir(exist_ok=False)
    path = directory / "default.ini"
    path.write_bytes(data)
    return dict(cross_key="g", source="pinned_default_with_letter_override",
                relative_path="session/user/input_config/default.ini",
                template_sha256=TEMPLATE_SHA256, sha256=hashlib.sha256(data).hexdigest())
