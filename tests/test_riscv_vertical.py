"""The RISC-V vertical-slice contract and its L3 log parser."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vertical", ROOT / "vertical.py")
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)


class L3Parser(unittest.TestCase):
    def test_failed_line_is_not_expectedly_failed(self):
        text = """\
Total Discovered Tests: 80655
  Skipped          :    59 (0.07%)
  Unsupported      : 15534 (19.26%)
  Passed           : 64916 (80.49%)
  Expectedly Failed:   146 (0.18%)
"""
        with tempfile.NamedTemporaryFile("w", suffix=".log",
                                         delete=False) as fh:
            fh.write(text)
            path = Path(fh.name)
        self.assertEqual(rv.parse_l3(path), {
            "discovered": 80655, "passed": 64916,
            "xfail": 146, "failed": 0,
        })

    def test_real_failed_line(self):
        text = """\
Total Discovered Tests: 10
  Passed           : 9
  Expectedly Failed: 1
  Failed           : 1
"""
        with tempfile.NamedTemporaryFile("w", suffix=".log",
                                         delete=False) as fh:
            fh.write(text)
            path = Path(fh.name)
        self.assertEqual(rv.parse_l3(path)["failed"], 1)


class FrozenSlice(unittest.TestCase):
    """`--verify-only --frozen` must pass from the committed oracle tree.

    CI has no /tmp artifacts and no LLVM build, so this is the only form of
    the RISC-V vertical check that can run there.
    """

    def test_frozen_artifacts_match_the_contract(self):
        c = json.loads((ROOT / "data" / "riscv-contract.json").read_text())
        out = rv.materialize_frozen("riscv")
        self.assertEqual(
            rv.verify(out, c, out / "u" / "queries.jsonl", "riscv",
                      ROOT / "data" / "riscv-contract.json",
                      l3_required=False), 0)


class Contract(unittest.TestCase):
    def test_contract_is_complete(self):
        c = json.loads((ROOT / "data" / "riscv-contract.json").read_text())
        self.assertEqual(c["target"], "riscv")
        self.assertEqual(len(c["snapshot"]["inc_sha256"]), 64)
        self.assertEqual(c["g"]["queries"], 6086)
        self.assertEqual(c["u"]["queries"], 20445)
        self.assertEqual(c["domain"]["configs"], 8)
        self.assertEqual(c["mir_l2"]["runs"], 4203)
        self.assertEqual(c["l3"]["failed"], 0)


class Targets(unittest.TestCase):
    def test_every_target_declares_the_same_interface(self):
        keys = {"contract", "inc", "corpus", "features", "end_to_end",
                "domain", "g_neg", "u_neg", "u_prefix", "allow_unanswerable"}
        for name, spec in rv.TARGETS.items():
            with self.subTest(target=name):
                self.assertEqual(set(spec), keys)
                self.assertTrue((ROOT / spec["contract"]).exists(),
                                "no contract for %s" % name)

    def test_every_contract_names_its_target(self):
        for name in rv.TARGETS:
            with self.subTest(target=name):
                c = json.loads((ROOT / "data" / ("%s-contract.json" % name))
                               .read_text())
                self.assertEqual(c["target"], name)
                self.assertEqual(c["g"]["disagree"], 0)
                self.assertEqual(c["u"]["disagree"], 0)
                self.assertEqual(c["domain"]["disagree"], 0)
                self.assertGreaterEqual(c["u_neg"]["disagree"], 1)
                self.assertGreaterEqual(c["g_neg"]["disagree"], 1)


if __name__ == "__main__":
    unittest.main()
