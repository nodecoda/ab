"""The RISC-V vertical-slice contract and its L3 log parser."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "gisel_ab" / "data"
from gisel_ab import vertical as rv  # noqa: E402


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
        c = json.loads((DATA / "riscv-contract.json").read_text())
        out = rv.materialize_frozen("riscv")
        self.assertEqual(
            rv.verify(out, c, out / "u" / "queries.jsonl", "riscv",
                      DATA / "riscv-contract.json",
                      l3_required=False), 0)


class Contract(unittest.TestCase):
    def test_contract_is_complete(self):
        c = json.loads((DATA / "riscv-contract.json").read_text())
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
                self.assertTrue((DATA / Path(spec["contract"]).name).exists(),
                                "no contract for %s" % name)

    def test_every_contract_names_its_target(self):
        for name in rv.TARGETS:
            with self.subTest(target=name):
                c = json.loads((DATA / ("%s-contract.json" % name))
                               .read_text())
                self.assertEqual(c["target"], name)
                self.assertEqual(c["g"]["disagree"], 0)
                self.assertEqual(c["u"]["disagree"], 0)
                self.assertEqual(c["domain"]["disagree"], 0)
                self.assertGreaterEqual(c["u_neg"]["disagree"], 1)
                self.assertGreaterEqual(c["g_neg"]["disagree"], 1)


class Provenance(unittest.TestCase):
    def test_leg_command_names_tree_and_build(self):
        cmd = rv.leg_command("e2e/run-u-end-to-end.sh", "x86", "/q", "/o",
                             tree="/tmp/tree-A", build="/tmp/build-B")
        self.assertEqual([str(x) for x in cmd[-4:]],
                         ["--tree", "/tmp/tree-A", "--build", "/tmp/build-B"])
        self.assertEqual(str(cmd[0]),
                         str(ROOT / "scripts" / "e2e" / "run-u-end-to-end.sh"))

    def test_contract_pin_prefers_the_flag_then_the_contract(self):
        contract = {"mir_l2": {"timeout": 63, "unsupported_run": 0}}
        self.assertEqual(rv.contract_pin(7, contract, "mir_l2", "timeout"), 7)
        self.assertEqual(rv.contract_pin(None, contract, "mir_l2", "timeout"),
                         63)
        self.assertIsNone(rv.contract_pin(None, None, "mir_l2", "timeout"))

    def test_pins_are_omitted_when_unknown(self):
        self.assertEqual(rv.pins(None, None), [])
        self.assertEqual(rv.pins(0, 2),
                         ["--expect-timeouts", "0",
                          "--expect-unsupported", "2"])



if __name__ == "__main__":
    unittest.main()
