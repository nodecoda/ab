"""mir-from-query: type spelling, shapes, sinks, buckets, preflight."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "mir_from_query", ROOT / "mir-from-query.py")
mfq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mfq)

SHAPES = mfq.load_jsonc(ROOT / "data" / "mir-shapes.jsonc")["opcodes"]
CONFIGS = json.loads((ROOT / "data" / "mir-configs.json").read_text())
X86 = CONFIGS["targets"]["x86"]["C1"]


def query(name, types=None, config="C1", mem=None, imms=None):
    return {"name": name, "types": types or [], "config": config, "mem": mem,
            "imms": imms or [], "kind": "equivalence", "rule": 0,
            "ruleset": "R_" + name, "reason": "first match for rule 0"}


class Types(unittest.TestCase):
    def test_scalar_spellings(self):
        for given, expected, width in [
                ("s7", "s7", 7), ("i32", "i32", 32), ("f64", "f64", 64),
                ("bf16", "f16", 16), ("p0:*", "p0", 64), ("p0:32", "p0", 64)]:
            self.assertEqual(mfq.mir_type(given), expected)
            self.assertEqual(mfq.bits(given, 64), width)

    def test_vector_spellings(self):
        for given, expected in [
                ("v4s32", "<4 x s32>"),
                ("v16i8", "<16 x s8>"),
                ("v2f32", "<2 x f32>"),
                ("v2bf16", "<2 x bf16>"),
                ("v2p0:64", "<2 x p0>"),
                ("nxv2p0:64", "<vscale x 2 x p0>")]:
            self.assertEqual(mfq.mir_type(given), expected)

    def test_vector_bits(self):
        self.assertEqual(mfq.bits("v2p0:64", 64), 128)
        self.assertEqual(mfq.bits("v2p0:64", 32), 64)
        self.assertEqual(mfq.bits("v16i8", 64), 128)

    def test_unknown_type_is_an_unbuildable_type(self):
        with self.assertRaises(mfq.Unbuildable) as caught:
            mfq.mir_type("x86_Vec128")
        self.assertEqual(caught.exception.bucket, "unbuildable_type")


class Build(unittest.TestCase):
    def test_every_def_gets_a_copy_sink(self):
        """The legalizer erases trivially dead instructions, so a def that
        nothing reads would make every rule mutation invisible."""
        text = mfq.build(query("G_ADD", ["s16"]), SHAPES, X86, 64)
        body = text.split("body:", 1)[1]
        self.assertIn("G_ADD", body)
        sinks = [line for line in body.splitlines() if " = COPY " in line]
        self.assertEqual(len(sinks), 1)
        self.assertIn(":_(s16) = COPY", sinks[0])

    def test_no_defs_means_no_sinks(self):
        text = mfq.build(query("G_STORE", ["s32", "p0"],
                               mem=["s32", 4]), SHAPES, X86, 64)
        self.assertNotIn("COPY", text.split("body:", 1)[1])

    def test_missing_shape_is_unbuildable(self):
        with self.assertRaises(mfq.Unbuildable) as caught:
            mfq.build(query("G_NOT_AN_OPCODE"), SHAPES, X86, 64)
        self.assertIn("no shape", caught.exception.reason)

    def test_skipped_opcodes_say_why(self):
        for opcode in ("G_PHI", "G_BRJT", "G_JUMP_TABLE"):
            with self.assertRaises(mfq.Unbuildable) as caught:
                mfq.build(query(opcode, ["s32"]), SHAPES, X86, 64)
            self.assertIn(mfq.SKIP[opcode], caught.exception.reason)

    def test_target_skip_says_why_and_leaves_other_targets_alone(self):
        """SPIR-V's pre-legalizer splits splats; asking the rule table
        directly hits an upstream out-of-range type index."""
        cfg = CONFIGS["targets"]["spirv"]["spirv32-kernel"]
        with self.assertRaises(mfq.Unbuildable) as caught:
            mfq.build(query("G_SPLAT_VECTOR", ["v32s1"], config="spirv32-kernel"),
                      SHAPES, cfg, 32, "spirv")
        self.assertEqual(caught.exception.bucket, "unbuildable_shape")
        self.assertIn("G_CONCAT_VECTORS", caught.exception.reason)
        # The same opcode is not skipped for a target that never asked.
        text = mfq.build(query("G_SPLAT_VECTOR", ["v4s32"]), SHAPES, X86, 64,
                         "x86")
        self.assertIn("G_SPLAT_VECTOR", text)

    def test_shuffle_mask_covers_every_lane(self):
        text = mfq.build(query("G_SHUFFLE_VECTOR", ["v4s32", "v4s32"]),
                         SHAPES, X86, 64)
        self.assertIn("shufflemask(0, 1, 2, 3)", text)

    def test_pointer_slot_accepts_a_vector_of_pointers(self):
        text = mfq.build(query("G_PTR_ADD", ["v2p0:64", "s64"]),
                         SHAPES, X86, 64)
        self.assertIn("<2 x p0>", text)

    def test_scalar_in_a_pointer_slot_is_rejected(self):
        with self.assertRaises(mfq.Unbuildable) as caught:
            mfq.build(query("G_LOAD", ["s32", "s32"], mem=["s32", 4]),
                      SHAPES, X86, 64)
        self.assertIn("slot 1 of G_LOAD is a pointer", caught.exception.reason)

    def test_run_line_carries_config_args(self):
        cfg = CONFIGS["targets"]["aarch64"]["small-cm"]
        text = mfq.build(query("G_ADD", ["s32"], config="small-cm"), SHAPES,
                         cfg, 64)
        self.assertIn("-code-model=small", text.splitlines()[0])
        self.assertIn("-global-isel-abort=1", text.splitlines()[0])


class Preflight(unittest.TestCase):
    def test_parse_failure_moves_the_file_to_unbuildable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mir = root / "q0.mir"
            mir.write_text("# RUN: llc -run-pass=legalizer %s -o -\n")
            index = [{"file": "q0.mir", "query": query("G_ADD", ["s32"]),
                      "bucket": "built"}]
            buckets = {"built": 1, "unbuildable_shape": 0}
            from collections import Counter
            reasons = Counter()
            per_opcode = Counter({("G_ADD", "built"): 1})

            class FakeProc:
                returncode = 1
                stderr = "*** Bad machine code: bad shape ***"

            with mock.patch.object(subprocess, "run",
                                   return_value=FakeProc()):
                mfq.reclassify(index, root, buckets, per_opcode, reasons,
                               Path("/bin/true"), None, 1)
            self.assertEqual(index[0]["bucket"], "unbuildable_shape")
            self.assertFalse(mir.exists())
            self.assertEqual(buckets["built"], 0)
            self.assertEqual(buckets["unbuildable_shape"], 1)

    def test_legalizer_refusal_is_not_a_parse_failure(self):
        """`unable to legalize` is an answer (both sides abort), not a
        malformed question, so the file has to stay."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mir = root / "q0.mir"
            mir.write_text("# RUN: llc -run-pass=legalizer %s -o -\n")

            class FakeProc:
                returncode = 1
                stderr = "LLVM ERROR: unable to legalize instruction: G_ADD"

            with mock.patch.object(subprocess, "run",
                                   return_value=FakeProc()):
                path, reason = mfq.preflight_one(mir, Path("/bin/true"), None)
            self.assertIsNone(reason)

    def test_preflight_runs_without_the_legalizer(self):
        captured = {}

        class FakeProc:
            returncode = 0
            stderr = ""

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            return FakeProc()

        with tempfile.TemporaryDirectory() as tmp:
            mir = Path(tmp) / "q0.mir"
            mir.write_text("# RUN: llc -run-pass=legalizer %s -o -\n")
            with mock.patch.object(subprocess, "run", side_effect=fake_run):
                mfq.preflight_one(mir, Path("/bin/true"), None)
        self.assertIn("-run-pass=none", captured["argv"])


class ShapeContract(unittest.TestCase):
    def test_table_loads_and_cites_every_entry(self):
        doc = mfq.load_jsonc(ROOT / "data" / "mir-shapes.jsonc")
        opcodes = mfq.validate_shapes(doc)
        self.assertGreater(len(opcodes), 100)

    def test_entry_without_source_is_rejected(self):
        doc = {"schema": 1, "opcodes": {"G_ADD": {"out": ["type0"],
                                                  "in": ["type0"]}}}
        with self.assertRaises(SystemExit):
            mfq.validate_shapes(doc)

    def test_wrong_schema_is_rejected(self):
        with self.assertRaises(SystemExit):
            mfq.validate_shapes({"schema": 2, "opcodes": {}})


class Configs(unittest.TestCase):
    def test_every_realizable_config_names_a_triple_and_width(self):
        for target, configs in CONFIGS["targets"].items():
            for name, cfg in configs.items():
                self.assertIn("triple", cfg, (target, name))
                self.assertIn("source", cfg, (target, name))
                if "mattr" in cfg:
                    self.assertIn(cfg["pointer_width"], (32, 64))

    def test_unrealizable_configs_have_no_mattr(self):
        self.assertNotIn("mattr", CONFIGS["targets"]["riscv"]["ristretto"])


if __name__ == "__main__":
    unittest.main()
