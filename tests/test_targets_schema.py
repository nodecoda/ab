"""targets/*.json is the only target registry.

The schema test fails on an unknown/missing field.  The parity test compares
the JSON with the tables that still live in vertical.py, mir_libs.py, l3.py,
swap-source-ctor.py and the shell scripts at git 32d66ce; a mismatch means a
migration would change behaviour quietly.
"""

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import targets  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "target-registry-pre-w2.json"


def norm(value):
    return re.sub(r"^\$(GISEL|ROOT|PWD)/", "", value)


def load_ab():
    spec = importlib.util.spec_from_file_location("ab_harness_targets",
                                                  ROOT / "ab.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SchemaTest(unittest.TestCase):
    def test_all_targets_validate(self):
        self.assertEqual(targets.check_all(), [])

    def test_every_target_file_has_a_schema_name(self):
        for path in sorted((ROOT / "targets").glob("*.json")):
            if path.name == "schema.json":
                continue
            doc = json.loads(path.read_text())
            self.assertEqual(doc["name"], path.stem)

    def test_unknown_field_is_rejected(self):
        doc = targets.load("x86")
        doc["bogus"] = 1
        errors = targets.validate(doc, targets.load_schema())
        self.assertTrue(any("unknown field 'bogus'" in error
                            for error in errors), errors)

    def test_missing_field_is_rejected(self):
        doc = targets.load("x86")
        del doc["contract"]
        errors = targets.validate(doc, targets.load_schema())
        self.assertTrue(any("missing field 'contract'" in error
                            for error in errors), errors)

    def test_swap_source_needs_a_ninja_target(self):
        doc = targets.load("x86")
        doc["ninja_target"] = None
        errors = targets.validate(doc, targets.load_schema())
        self.assertTrue(any("ninja_target" in error for error in errors),
                        errors)

    def test_unknown_target_is_a_harness_error(self):
        ab = load_ab()
        with self.assertRaises(ab.HarnessError) as caught:
            ab.load_target("nope")
        self.assertIn("unknown target", str(caught.exception))

    def test_cli_check_and_env(self):
        proc = subprocess.run([sys.executable, str(ROOT / "targets.py"),
                               "check"], cwd=ROOT, capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("10 files valid", proc.stdout)
        proc = subprocess.run([sys.executable, str(ROOT / "targets.py"),
                               "get", "mips", "diff_policy.allow_ref_asserts"],
                              cwd=ROOT, capture_output=True, text=True)
        self.assertEqual((proc.returncode, proc.stdout.strip()), (0, "9"))
        proc = subprocess.run([sys.executable, str(ROOT / "targets.py"),
                               "env", "x86"], cwd=ROOT, capture_output=True,
                              text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        namespace = {}
        exec(proc.stdout, {}, namespace)
        self.assertEqual(namespace["T_TARGET"], "x86")
        self.assertEqual(namespace["T_U_NEG"], "G_SUB")
        self.assertEqual(namespace["T_EXPECTED_QUERIES"], "3014")
        self.assertEqual(namespace["T_U_BUILDER"], "build-x86-ctor-runner.sh")

    def test_verify_without_baseline_inc_is_a_clean_error(self):
        ab = load_ab()
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state" / "baseline"
            state.mkdir(parents=True)
            (state / "provenance.json").write_text(
                json.dumps({"inc_sha256": None}))
            proc = subprocess.run(
                [sys.executable, str(ROOT / "ab.py"), "verify",
                 "--target", "m68k", "--tree", tmp, "--build", tmp,
                 "--state", str(Path(tmp) / "state")],
                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("no baseline_inc", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertIsNotNone(ab)


class ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = json.loads(FIXTURE.read_text())
        cls.doc = {path.stem: json.loads(path.read_text())
                   for path in (ROOT / "targets").glob("*.json")
                   if path.name != "schema.json"}

    def test_vertical_table(self):
        for name, old in self.old["vertical"].items():
            new = self.doc[name]
            self.assertEqual(new["contract"], old["contract"], name)
            self.assertEqual(new["artifact"], old["inc"], name)
            self.assertEqual(Path(norm(old["corpus"])).name, Path(new["source"]).name, name)
            self.assertEqual(Path(new["features"]).name, Path(old["features"]).name, name)
            self.assertEqual(new["e2e"], old["end_to_end"], name)
            self.assertEqual(new["domain"], old["domain"], name)
            self.assertEqual(new["g_neg"], old["g_neg"], name)
            self.assertEqual(new["u_neg"], old["u_neg"], name)
            self.assertEqual(new["u_prefix"], old["u_prefix"], name)
            self.assertEqual(new["allow_unanswerable"],
                             old["allow_unanswerable"], name)

    def test_mir_libs_table(self):
        for name, test_dir in self.old["mir_libs"]["test_dir"].items():
            self.assertEqual(self.doc[name]["test_dir"], test_dir, name)
            self.assertEqual(self.doc[name]["mir"]["swappable"],
                             name in self.old["mir_libs"]["swappable"], name)
        self.assertFalse(self.doc["x86-ctor"]["mir"]["swappable"])

    def test_l3_table(self):
        names = self.old["l3"]["names"]
        for name in self.old["l3"]["targets"]:
            self.assertEqual(self.doc[name]["test_dir"], names[name], name)
            self.assertTrue(self.doc[name]["l3"], name)
        for name, doc in self.doc.items():
            if name not in self.old["l3"]["targets"]:
                self.assertFalse(doc["l3"], name)

    def test_run_u_table(self):
        for name, old in self.old["run_u"].items():
            new = self.doc[name]
            self.assertEqual(new["u_builder"], norm(old["builder"]), name)
            self.assertEqual(new["inc_name"], old["inc_name"], name)
            self.assertEqual(Path(norm(old["corpus"])).name, Path(new["source"]).name, name)

    def test_run_g_negative_table(self):
        for name, old in self.old["run_g_negative"].items():
            new = self.doc[name]
            self.assertEqual(Path(norm(old["corpus"])).name, Path(new["source"]).name, name)
            self.assertEqual(new["e2e"], norm(old["script"]), name)

    def test_e2e_policy(self):
        for name, old in self.old["e2e"].items():
            new = self.doc[name]
            self.assertEqual(new["e2e"], norm(old["script"]), name)
            policy = new["diff_policy"]
            self.assertEqual(policy["expected_queries"],
                             old["expected_queries"], name)
            self.assertEqual(policy["allow_ref_asserts"],
                             old["allow_ref_asserts"], name)
            self.assertEqual(policy["expect_unanswerable"],
                             old["expect_unanswerable"], name)

    def test_swap_source_ctor_source_and_inc(self):
        for name, old in self.old["swap_source_ctor"].items():
            new = self.doc[name]
            self.assertEqual(new["touch_source"], old["source"], name)
            self.assertEqual(new["inc_name"], old["inc"], name)


if __name__ == "__main__":
    unittest.main()
