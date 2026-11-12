"""MIR library plumbing: target specs, snapshot/restore, lock, llc runner."""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import mir_libs  # noqa: E402


def completed(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


class TargetSpecs(unittest.TestCase):
    def test_every_adapter_has_a_spec_and_a_test_dir(self):
        for name in mir_libs.SWAPPABLE:
            spec = mir_libs.load_target(name)
            self.assertEqual(spec["name"], name)
            self.assertTrue(spec["library"].endswith("CodeGen.so.24.0git"))
            self.assertIn(name, mir_libs.TEST_DIR)

    def test_every_swappable_target_has_a_constructor_spec(self):
        # SWAPPABLE drives mir-replay --target; the swap script is the other
        # half of the same contract.  A target in one and not the other fails
        # at the end of a rebuild instead of here.
        spec = importlib.util.spec_from_file_location(
            "swap_source_ctor", ROOT / "swap-source-ctor.py")
        swap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(swap)
        self.assertEqual(set(mir_libs.SWAPPABLE), set(swap.TARGETS))

    def test_unknown_target_is_an_error(self):
        with self.assertRaises(mir_libs.MirError):
            mir_libs.load_target("not-a-target")

    def test_ninja_target_is_derived_from_the_library(self):
        spec = {"library": "lib/Target/X86/libLLVMX86CodeGen.so.24.0git"}
        self.assertEqual(mir_libs.ninja_target(spec), "libLLVMX86CodeGen.so")

    def test_explicit_ninja_target_wins(self):
        spec = {"library": "lib/x.so", "ninja_target": "custom"}
        self.assertEqual(mir_libs.ninja_target(spec), "custom")


class PrepareTarget(unittest.TestCase):
    """Snapshot / swap / build / restore, with ninja and swap faked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tree = self.root / "tree"
        self.build = self.root / "build"
        source = self.tree / "llvm/lib/Target/X86/GISel/X86LegalizerInfo.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("// official constructor\n")
        lib = self.build / "lib" / "libLLVMX86CodeGen.so.24.0git"
        lib.parent.mkdir(parents=True)
        lib.write_bytes(b"official-bytes")
        self.source = source
        self.lib = lib
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, cmd, cwd=None, env=None):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        if "status" in cmd:
            return completed()
        if any(part.endswith("swap-source-ctor.py") for part in cmd):
            if "apply" in cmd:
                self.source.write_text("// generated constructor\n")
            else:
                self.source.write_text("// official constructor\n")
            return completed()
        if any(part.endswith("gisel") or part == "-m" for part in cmd):
            out = Path(cmd[cmd.index("--out") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("// inc\n")
            return completed()
        if any(part.endswith("inject-missing-opcode.py") for part in cmd):
            Path(cmd[-1]).write_text("// mutant inc\n")
            return completed()
        if cmd and cmd[0] == mir_libs.NINJA:
            body = self.source.read_text()
            self.lib.write_bytes(
                b"generated-bytes" if "generated" in body else b"official-bytes")
            return completed()
        raise AssertionError("unexpected command: %r" % (cmd,))

    def test_swap_build_snapshot_and_restore(self):
        out = self.root / "out"
        with mock.patch.object(mir_libs, "run", side_effect=self.fake_run):
            info = mir_libs.prepare_target(
                "x86", self.tree, self.build, out, gisel=self.root / "gisel")
        self.assertEqual(info["source_sha256"],
                         mir_libs.sha256(self.source))
        self.assertTrue(info["baseline_lib_restored_exactly"])
        self.assertEqual(info["official_lib_sha256"],
                         mir_libs.sha256(Path(info["official_lib"])))
        self.assertNotEqual(info["ours_lib_sha256"], info["official_lib_sha256"])
        self.assertEqual(self.lib.read_bytes(), b"official-bytes")
        self.assertEqual(self.source.read_text(), "// official constructor\n")
        self.assertEqual(info["inc_sha256"],
                         mir_libs.sha256(Path(info["inc"])))
        self.assertIsNone(info["mutate_opcode"])

    def test_dirty_tree_is_refused_before_touching_anything(self):
        def dirty(cmd, cwd=None, env=None):
            cmd = [str(part) for part in cmd]
            if "status" in cmd:
                return completed(" M llvm/lib/Target/X86/GISel/X86LegalizerInfo.cpp\n")
            raise AssertionError("should not run %r" % (cmd,))

        with mock.patch.object(mir_libs, "run", side_effect=dirty):
            with self.assertRaises(mir_libs.MirError):
                mir_libs.prepare_target("x86", self.tree, self.build,
                                        self.root / "out",
                                        gisel=self.root / "gisel")

    def test_failed_build_still_restores_the_source(self):
        def fail_on_ninja(cmd, cwd=None, env=None):
            cmd = [str(part) for part in cmd]
            if cmd and cmd[0] == mir_libs.NINJA:
                raise mir_libs.MirError("build failed")
            return self.fake_run(cmd, cwd, env)

        with mock.patch.object(mir_libs, "run", side_effect=fail_on_ninja):
            with self.assertRaises(mir_libs.MirError):
                mir_libs.prepare_target("x86", self.tree, self.build,
                                        self.root / "out",
                                        gisel=self.root / "gisel")
        self.assertEqual(self.source.read_text(), "// official constructor\n")

    def test_negative_control_snapshots_a_mutant(self):
        out = self.root / "out"
        with mock.patch.object(mir_libs, "run", side_effect=self.fake_run):
            info = mir_libs.prepare_target(
                "x86", self.tree, self.build, out, gisel=self.root / "gisel",
                mutate_opcode="G_ADD")
        self.assertEqual(info["mutate_opcode"], "G_ADD")
        self.assertIn("ours-negative", info["ours_lib"])
        self.assertNotEqual(info["inc_sha256"],
                            mir_libs.sha256(out / "inc" / "X86LegalizerInfo.inc"))


class LockTest(unittest.TestCase):
    def test_a_second_writer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lock"
            with mir_libs.Lock(path):
                with self.assertRaises(mir_libs.MirError):
                    with mir_libs.Lock(path):
                        pass
            with mir_libs.Lock(path):
                pass


class RunLlc(unittest.TestCase):
    def test_timeout_is_reported_not_raised(self):
        result = mir_libs.run_llc(Path(sys.executable), Path("/tmp"),
                                  ["-c", "import time; time.sleep(5)"],
                                  timeout=0.2)
        self.assertTrue(result["timeout"])
        self.assertIsNone(result["rc"])

    def test_library_dir_is_prepended_to_the_search_path(self):
        result = mir_libs.run_llc(
            Path(sys.executable), Path("/opt/fake-libs"),
            ["-c", "import os; print(os.environ['LD_LIBRARY_PATH'])"])
        self.assertEqual(result["rc"], 0)
        first = result["out"].strip().split(os.pathsep)[0]
        self.assertEqual(first, "/opt/fake-libs")


if __name__ == "__main__":
    unittest.main()
