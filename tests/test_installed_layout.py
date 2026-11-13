"""The wheel-only layout: no checkout next to the install.

These tests fake a site-packages tree and assert that ``gisel-ab`` finds the
corpus and the pin the wheels ship, instead of a sibling checkout that does
not exist on a user's machine.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import gisel_ab
from gisel_ab import cli, doctor, paths, suite

ROOT = Path(__file__).resolve().parents[1]


class InstalledGisel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.site = root / "site-packages"
        self.pkg = self.site / "gisel"
        (self.pkg / "data" / "corpus").mkdir(parents=True)
        (self.pkg / "data" / "cases").mkdir(parents=True)
        (self.pkg / "__init__.py").write_text("")
        (self.pkg / "data" / "corpus" / "X.gisel").write_text("x\n")
        (self.pkg / "data" / "cases" / "x-features.json").write_text("{}\n")
        self.root = root
        self.patches = [
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(gisel_ab, "AB_ROOT", root / "ab"),
            mock.patch.object(gisel_ab, "_gisel_package_dir",
                              return_value=self.pkg),
        ]
        self.patches[0].start()
        os.environ.pop("GISEL_SRC", None)
        for patch in self.patches[1:]:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def test_src_is_the_directory_that_makes_the_import_work(self):
        self.assertEqual(gisel_ab.gisel_src(), self.site)

    def test_data_comes_from_the_wheel_when_there_is_no_checkout(self):
        self.assertEqual(gisel_ab.gisel_data("corpus"),
                         self.pkg / "data" / "corpus")
        self.assertEqual(gisel_ab.gisel_data("cases"),
                         self.pkg / "data" / "cases")

    def test_suite_paths_resolve_inside_the_wheel(self):
        directory = self.pkg / "data" / "suite" / "m68k"
        directory.mkdir(parents=True)
        corpus = suite._gisel_path(
            directory, "../../../gisel/tests/corpus/X.gisel")
        features = suite._gisel_path(
            directory, "../../../gisel/tests/cases/x-features.json")
        self.assertEqual(corpus, self.pkg / "data" / "corpus" / "X.gisel")
        self.assertEqual(features,
                         self.pkg / "data" / "cases" / "x-features.json")

    def test_a_sibling_checkout_still_wins(self):
        checkout = self.root / "gisel"
        (checkout / "gisel").mkdir(parents=True)
        (checkout / "gisel" / "__init__.py").write_text("")
        (checkout / "tests" / "corpus").mkdir(parents=True)
        (checkout / "tests" / "corpus" / "X.gisel").write_text("y\n")
        self.assertEqual(gisel_ab.gisel_src(), checkout)
        self.assertEqual(gisel_ab.gisel_data("corpus"),
                         checkout / "tests" / "corpus")


class GiselChildEnv(unittest.TestCase):
    def test_an_installed_gisel_needs_no_pythonpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site-packages"
            (site / "gisel").mkdir(parents=True)
            (site / "gisel" / "__init__.py").write_text("")
            with mock.patch.object(suite, "gisel_src", return_value=site):
                env = suite._gisel_env({})
        self.assertNotIn("PYTHONPATH", env)

    def test_a_checkout_is_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            checkout = Path(tmp)
            (checkout / "gisel").mkdir()
            (checkout / "gisel" / "__init__.py").write_text("")
            with mock.patch.object(suite, "gisel_src", return_value=checkout):
                env = suite._gisel_env({})
            self.assertEqual(env["PYTHONPATH"], str(checkout))

    def test_gisel_src_still_shadows_an_install(self):
        env = suite._gisel_env({"GISEL_SRC": "/tmp/checkout"})
        self.assertEqual(env["PYTHONPATH"].split(os.pathsep)[0], "/tmp/checkout")

    def test_an_existing_entry_is_not_duplicated(self):
        env = suite._gisel_env({"GISEL_SRC": "/c",
                                "PYTHONPATH": "/c:/elsewhere"})
        self.assertEqual(env["PYTHONPATH"], "/c:/elsewhere")


class PinFallback(unittest.TestCase):
    def test_installed_anchor_pin_is_used_when_there_is_no_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            anchor = root / "site-packages" / "gisel_anchor"
            (anchor / "importer" / "data").mkdir(parents=True)
            pin = anchor / "importer" / "data" / "PIN.json"
            pin.write_text("{}\n")
            module = types.ModuleType("gisel_anchor")
            module.__file__ = str(anchor / "__init__.py")
            with mock.patch.dict(sys.modules, {"gisel_anchor": module}), \
                    mock.patch.object(doctor.paths, "sibling",
                                      return_value=root / "nowhere"):
                self.assertEqual(doctor._pin_path(), pin)

    def test_gs_pin_wins(self):
        with mock.patch.dict(os.environ, {"GS_PIN": "/tmp/explicit.json"}):
            self.assertEqual(doctor._pin_path(), Path("/tmp/explicit.json"))


class Version(unittest.TestCase):
    def test_version_flag_prints_a_semver(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["--version"]), 0)
        match = re.fullmatch(r"gisel-ab (\d+\.\d+\.\d+)\n", out.getvalue())
        self.assertIsNotNone(match, out.getvalue())

    def test_checkout_version_matches_pyproject(self):
        declared = re.search(r'^version\s*=\s*"([^"]+)"',
                             (ROOT / "pyproject.toml").read_text(), re.M)
        self.assertIsNotNone(declared)
        self.assertEqual(cli._version(), declared.group(1))


if __name__ == "__main__":
    unittest.main()
