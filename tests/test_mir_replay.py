"""MIR replay: RUN parsing, crash normalisation, buckets, negative control."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("mir_replay", ROOT / "mir-replay.py")
mr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mr)
import mir_libs  # noqa: E402


def run_line(*lines):
    return "\n".join("# RUN: " + line for line in lines)


class RunParsing(unittest.TestCase):
    def write(self, body):
        handle = tempfile.NamedTemporaryFile("w", suffix=".mir", delete=False)
        handle.write(body + "\n")
        handle.handle if False else handle.close()
        return Path(handle.name)

    def test_continuation_is_joined(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer \\",
            "  %s -o - | FileCheck %s"))
        self.assertEqual(mr.read_run_lines(path),
                         ["llc -mtriple=x86_64-- -run-pass=legalizer   %s -o - "
                          "| FileCheck %s"])

    def test_filecheck_and_redirects_are_dropped(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer %s 2>&1 | FileCheck %s"))
        argv, expect_failure = mr.parse_run(
            mr.read_run_lines(path)[0], path, Path("/tmp/tmp0"))
        self.assertFalse(expect_failure)
        self.assertNotIn("|", " ".join(argv))
        self.assertNotIn("2>&1", argv)
        self.assertEqual(argv[-2:], ["-o", "-"])
        self.assertIn(str(path), argv)

    def test_redirect_target_does_not_become_an_input_file(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer %s 2> %t.err "
            "| FileCheck %s"))
        argv, _ = mr.parse_run(mr.read_run_lines(path)[0], path,
                               Path("/tmp/tmp0"))
        self.assertNotIn("2>", argv)
        self.assertFalse(any(arg.endswith(".err") for arg in argv))
        self.assertEqual(argv.count(str(path)), 1)

    def test_joined_redirect_is_dropped(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer -pass-remarks-missed='gisel*' "
            "%s -o - 2>%t | FileCheck %s"))
        argv, _ = mr.parse_run(mr.read_run_lines(path)[0], path,
                               Path("/tmp/tmp0"))
        self.assertNotIn("2>%t", argv)

    def test_fd_redirect_is_dropped(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer %s -o - 2>&1 "
            "| FileCheck %s"))
        argv, _ = mr.parse_run(mr.read_run_lines(path)[0], path,
                               Path("/tmp/tmp0"))
        self.assertNotIn("2>&1", argv)

    def test_not_sets_expect_failure_and_keeps_llc(self):
        path = self.write(run_line(
            "not --crash llc -mtriple=aarch64-- -run-pass=legalizer %s -o -"))
        argv, expect_failure = mr.parse_run(
            mr.read_run_lines(path)[0], path, Path("/tmp/tmp0"))
        self.assertTrue(expect_failure)
        # `not` and the command name are both consumed: the runner supplies
        # the llc path itself.
        self.assertEqual(argv[0], "-mtriple=aarch64--")

    def test_non_legalizer_pass_is_rejected(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=regbankselect %s -o -"))
        argv, reason = mr.parse_run(
            mr.read_run_lines(path)[0], path, Path("/tmp/tmp0"))
        self.assertIsNone(argv)
        self.assertIn("legalizer", reason)

    def test_unknown_substitution_is_rejected(self):
        path = self.write(run_line(
            "llc -mtriple=x86_64-- -run-pass=legalizer %S -o -"))
        argv, reason = mr.parse_run(
            mr.read_run_lines(path)[0], path, Path("/tmp/tmp0"))
        self.assertIsNone(argv)
        self.assertIn("%S", reason)


class Normalisation(unittest.TestCase):
    def test_addresses_are_erased(self):
        left = " #0 0x00007fe6533a1372 foo\n basic block: %bb.0  (0x56538713aa30)"
        right = " #0 0x00007f36b8085372 foo\n basic block: %bb.0  (0x55cd68ec9b00)"
        self.assertEqual(mr.normalize(left), mr.normalize(right))
        self.assertIn("0x?", mr.normalize(left))

    def test_non_address_text_still_differs(self):
        self.assertNotEqual(mr.normalize("LLVM ERROR: a"),
                            mr.normalize("LLVM ERROR: b"))


def fake_run(rc=0, out="", err=""):
    return {"rc": rc, "timeout": False, "out": out, "err": err}


class Buckets(unittest.TestCase):
    def replay(self, official, ours, command=None, expect_not=False):
        command = command or (
            "%sllc -mtriple=x86_64-- -run-pass=legalizer %%s -o -"
            % ("not --crash " if expect_not else ""))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.root = root
            mir = root / "a.mir"
            mir.write_text("--- |\n")
            (root / "out").mkdir()
            budget = [5]

            def take():
                if budget[0] <= 0:
                    return False
                budget[0] -= 1
                return True

            with mock.patch.object(mir_libs, "run_llc",
                                   side_effect=[official, ours]):
                result = mr.replay_file(
                    "x86", mir, [command], root / "llc",
                    root / "official", root / "ours", root / "out",
                    10.0, take, root)
            record = result["runs"][0]
            if "detail" in record:
                self.detail_exists = Path(record["detail"]).exists()
        return record

    def test_identical_success_is_same(self):
        self.assertEqual(self.replay(fake_run(), fake_run())["status"], "same")

    def test_identical_failure_is_both_abort(self):
        record = self.replay(fake_run(1, err="LLVM ERROR: x"),
                             fake_run(1, err="LLVM ERROR: x"))
        self.assertEqual(record["status"], "both_abort")

    def test_crash_addresses_do_not_make_a_diff(self):
        official = fake_run(-6, err="stack 0x56538713aa30\nLLVM ERROR: x")
        ours = fake_run(-6, err="stack 0x557d677b0530\nLLVM ERROR: x")
        record = self.replay(official, ours, expect_not=True)
        self.assertEqual(record["status"], "both_abort")
        self.assertTrue(record["expect_failure"])

    def test_real_difference_is_a_diff(self):
        record = self.replay(fake_run(), fake_run(0, out="other"))
        self.assertEqual(record["status"], "diff")
        self.assertTrue(self.detail_exists)

    def test_timeout_wins_over_output(self):
        timed = {"rc": None, "timeout": True, "out": "", "err": ""}
        self.assertEqual(self.replay(timed, fake_run())["status"], "timeout")

    def test_out_of_layer_when_pass_is_not_legalizer(self):
        record = self.replay(
            None, None,
            command="llc -mtriple=x86_64-- -run-pass=regbankselect %s -o -")
        self.assertEqual(record["status"], "out_of_layer")


class Aggregate(unittest.TestCase):
    def test_identity_holds_and_sums(self):
        results = [
            {"target": "x86", "runs": [
                {"status": "same"}, {"status": "diff"},
                {"status": "out_of_layer"}, {"status": "unsupported_run"}]},
            {"target": "x86", "runs": [{"status": "both_abort"}]},
        ]
        per_target, totals = mr.aggregate(results, ["x86"])
        mr.check_identity(totals)
        self.assertEqual(totals["all_run_lines"], 5)
        self.assertEqual(totals["out_of_layer"], 1)
        self.assertEqual(totals["runs"], 4)
        self.assertEqual(per_target["x86"]["files"], 2)

    def test_broken_identity_is_reported(self):
        totals = {"all_run_lines": 1, "runs": 2, "same": 1, "both_abort": 0,
                  "diff": 0, "timeout": 0, "unsupported_run": 0,
                  "out_of_layer": 0}
        with self.assertRaises(mir_libs.MirError):
            mr.check_identity(totals)


if __name__ == "__main__":
    unittest.main()
