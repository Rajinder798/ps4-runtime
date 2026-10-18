# SPDX-FileCopyrightText: 2026 Rajinder Singh
# SPDX-License-Identifier: GPL-2.0-or-later
# See LICENSE in the project root for the full license text.

"""Portable evidence-policy tests; real link evidence is checked after engine builds."""
import copy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_engine_linkage as audit


class LinkageTests(unittest.TestCase):
    def setUp(self):
        self.targets = [dict(name="shadps4", sources=[dict(path="src/core/libraries/ajm/ajm_aac.cpp")],
                             compileGroups=[dict(includes=[dict(path="source/src")])],
                             link=dict(commandFragments=[dict(fragment="avcodec.lib avutil.lib")]))]
        self.link_map = " " * 4096 + " ff_aac_decoder AjmAacDecoder "

    def test_complete_evidence_keeps_release_hold(self):
        result = audit.inspect(self.targets, self.link_map)
        self.assertTrue(result["fdk_sources_absent"])
        self.assertTrue(result["fdk_symbols_absent"])
        self.assertFalse(result["upstream_redistribution_approved"])

    def test_each_active_graph_location_rejects_fdk(self):
        mutations = [lambda t: t.append(dict(name="fdk-aac")),
                     lambda t: t[0]["sources"].append(dict(path="source/externals/aacdec/lib.cpp")),
                     lambda t: t[0]["compileGroups"][0]["includes"].append(dict(path=r"C:\SRC\FDK-AAC\include")),
                     lambda t: t[0]["link"]["commandFragments"].append(dict(fragment='"fdk-aac.lib"'))]
        for change in mutations:
            target = copy.deepcopy(self.targets)
            change(target)
            with self.subTest(change=change), self.assertRaises(ValueError):
                audit.inspect(target, self.link_map)

    def test_symbols_and_objects_reject_fdk(self):
        for name in ("aacDecoder_Fill", "aacDecoder_Open", "CAacDecoder_Init", "fdk-aac.lib:decoder.obj"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.inspect(self.targets, self.link_map + name)

    def test_missing_or_short_evidence_fails(self):
        variants = [([], self.link_map), (self.targets, "ff_aac_decoder AjmAacDecoder"),
                    ([dict(name="other")], self.link_map),
                    (self.targets, self.link_map.replace("ff_aac_decoder", "other")),
                    (self.targets, self.link_map.replace("AjmAacDecoder", "other"))]
        for targets, text in variants:
            with self.subTest(targets=targets), self.assertRaises(ValueError):
                audit.inspect(targets, text)


if __name__ == "__main__":
    unittest.main()
