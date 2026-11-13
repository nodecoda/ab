"""doctor's gisel-pin check: match, installed mismatch, checkout mismatch."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gisel_ab import doctor  # noqa: E402


def _fake(version: str, location: Path) -> types.ModuleType:
    module = types.ModuleType("gisel")
    module.__version__ = version
    module.__file__ = str(location)
    return module


class GiselPin(unittest.TestCase):
    def test_a_matching_version_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _fake("0.3.0", Path(d) / "site-packages" / "gisel" / "__init__.py")
            with mock.patch.dict(sys.modules, {"gisel": fake}):
                check = doctor._gisel_compat()
        self.assertEqual(check.name, "gisel-pin")
        self.assertEqual(check.status, doctor.OK)
        self.assertIn("matches the cohort", check.detail)

    def test_an_installed_mismatch_fails_with_the_pin_command(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _fake("0.2.0", Path(d) / "site-packages" / "gisel" / "__init__.py")
            with mock.patch.dict(sys.modules, {"gisel": fake}):
                check = doctor._gisel_compat()
        self.assertEqual(check.status, doctor.FAIL)
        self.assertIn("pip install gisel==", check.fix)

    def test_a_checkout_mismatch_only_warns(self):
        with tempfile.TemporaryDirectory() as d:
            fake = _fake("0.2.0", Path(d) / "gisel" / "__init__.py")
            with mock.patch.dict(sys.modules, {"gisel": fake}):
                check = doctor._gisel_compat()
        self.assertEqual(check.status, doctor.WARN)
        self.assertIn("cohort pins", check.detail)


if __name__ == "__main__":
    unittest.main()
