"""A deliberate assert() must leave a file:line behind for the answer row.

This compiles a two-query programme against query-recovery.h: one query that
returns, one that asserts.  It is the only test that exercises the
`__assert_fail` interposition for real, so it needs the LLVM headers and
libLLVMSupport; it skips when they are not where the workspace puts them.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get("AB_LLVM_BUILD", "/home/ubuntu/llvm/builds/explore"))
TREE = Path(os.environ.get("AB_LLVM_TREE", "/home/ubuntu/llvm/trees/explore"))

PROGRAM = r'''
#include "query-recovery.h"

#include <cassert>
#include <cstdio>

static void Report(const char *What, bool Completed, const char *Site) {
  std::printf("%s %d %s\n", What, (int)Completed, Site);
}

int main() {
  bool Clean = ab::runQuery([] {});
  Report("clean", Clean, ab::detail::Site);

  bool Aborted = ab::runQuery([] { assert(false && "deliberate"); });
  Report("aborted", Aborted, ab::detail::Site);

  // report_fatal_error() has no file:line; the message must still classify.
  bool Fatal = ab::runQuery(
      [] { llvm::report_fatal_error("boom without a location"); });
  Report("fatal", Fatal, ab::detail::Site);

  bool Unreachable = ab::runQuery(
      [] { llvm_unreachable("deliberate unreachable"); });
  Report("unreachable", Unreachable, ab::detail::Site);

  // The site must not leak into the next query.
  bool Again = ab::runQuery([] {});
  Report("clean", Again, ab::detail::Site);
  return 0;
}
'''.lstrip()


def toolchain():
    cxx = shutil.which(os.environ.get("CXX", "g++"))
    support = BUILD / "lib" / "libLLVMSupport.so"
    if not any((BUILD / "lib").glob("libLLVMSupport.so*")):
        support = None
    if cxx is None or support is None:
        return None
    if not (TREE / "llvm" / "include" / "llvm" / "ADT" / "StringRef.h").exists():
        return None
    return cxx


class QueryRecovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cxx = toolchain()
        if cls.cxx is None:
            raise unittest.SkipTest("needs g++, LLVM headers and libLLVMSupport")
        cls.tmp = Path(tempfile.mkdtemp(prefix="ab-recovery-"))
        (cls.tmp / "t_query_recovery.cpp").write_text(PROGRAM)
        cls.binary = cls.tmp / "t_query_recovery"
        cmd = [
            cls.cxx, "-std=c++17", "-fno-exceptions", "-fno-rtti",
            "-I", str(ROOT),
            "-I", str(BUILD / "include"),
            "-I", str(TREE / "llvm" / "include"),
            str(cls.tmp / "t_query_recovery.cpp"),
            "-rdynamic", "-fuse-ld=lld",
            "-Wl,-rpath," + str(BUILD / "lib"),
            "-L", str(BUILD / "lib"), "-lLLVMSupport",
            "-lpthread", "-ldl", "-lz",
            "-o", str(cls.binary),
        ]
        built = subprocess.run(cmd, capture_output=True, text=True)
        if built.returncode != 0:
            raise unittest.SkipTest("could not build fixture:\n" + built.stderr)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "tmp", None):
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_fixture(self):
        done = subprocess.run([str(self.binary)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return [line.split(" ", 2) for line in done.stdout.splitlines()]

    def test_abort_reports_its_site(self):
        clean, aborted, fatal, unreachable, again = self.run_fixture()
        self.assertEqual(clean[:2], ["clean", "1"])
        self.assertEqual(aborted[:2], ["aborted", "0"])
        self.assertEqual(fatal[:2], ["fatal", "0"])
        self.assertEqual(unreachable[:2], ["unreachable", "0"])
        self.assertEqual(again[:2], ["clean", "1"])

    def test_fatal_error_keeps_a_message_site(self):
        _, _, fatal, _, _ = self.run_fixture()
        self.assertEqual(fatal[2], "fatal:boom without a location")

    def test_site_is_the_assertion_not_the_query(self):
        _, aborted, _, _, again = self.run_fixture()
        self.assertTrue(aborted[2].startswith("t_query_recovery.cpp:"),
                        aborted[2])
        line = int(aborted[2].split(":")[1])
        self.assertGreater(line, 0)
        self.assertEqual(again[2], "", "site leaked into the next query")

    def test_unreachable_is_not_lost(self):
        _, _, _, unreachable, _ = self.run_fixture()
        self.assertTrue(unreachable[2].startswith("t_query_recovery.cpp:"),
                        unreachable[2])

    def test_source_keeps_the_fatal_handler_installed(self):
        text = (ROOT / "query-recovery.h").read_text()
        self.assertIn("install_fatal_error_handler", text)
        self.assertIn('dlsym(RTLD_NEXT, "__assert_fail")', text)


if __name__ == "__main__":
    unittest.main()
