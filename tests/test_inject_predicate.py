import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ip = _load("inject-predicate")


INC = """\
  getActionDefinitionsBuilder(G_ADD)
      .coreMinScalar([](const LegalityQuery &) { return true; }, 0, X_s8)
      .coreLegalIf([=](const LegalityQuery &Query) { return (A) && (B); });
  getActionDefinitionsBuilder(G_LOAD)
      .coreLegalIf([=](const LegalityQuery &Query) { return X_Is64Bit; });
"""


class InjectPredicateTest(unittest.TestCase):
    def run_inject(self, opcode, mode, rule=0):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "base.inc"
            out = Path(d) / "out.inc"
            expect = Path(d) / "expect.json"
            src.write_text(INC)
            rc = ip.main(["inject-predicate.py", str(src), opcode, mode,
                          str(out), "--rule", str(rule),
                          "--expect", str(expect)])
            self.assertEqual(rc, 0)
            return out.read_text(), json.loads(expect.read_text())

    def test_widen_drops_a_conjunct(self):
        text, expect = self.run_inject("G_ADD", "widen", rule=1)
        self.assertIn("return (A);", text)
        self.assertNotIn("(A) && (B)", text)
        self.assertEqual(expect["predicate_after"], "(A)")

    def test_narrow_makes_the_rule_unmatchable(self):
        text, expect = self.run_inject("G_ADD", "narrow", rule=1)
        self.assertIn("return ((A) && (B)) && false;", text)
        self.assertEqual(expect["predicate_after"], "((A) && (B)) && false")

    def test_minus_one_skips_the_unconditional_rule(self):
        text, expect = self.run_inject("G_ADD", "widen", rule=-1)
        self.assertEqual(expect["rule"], 1)
        self.assertEqual(expect["predicate_before"], "(A) && (B)")
        self.assertIn("return true;", text)

    def test_unknown_opcode_is_a_usage_error(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "base.inc"
            src.write_text(INC)
            rc = ip.main(["inject-predicate.py", str(src), "G_NOPE", "widen",
                          str(Path(d) / "out.inc")])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
