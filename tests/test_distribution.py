"""The composite action and the pre-commit hook are installable artifacts."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIVEN = Path(__file__).resolve().parents[2] / "gisel"


class CompositeAction(unittest.TestCase):
    def test_action_is_well_formed(self):
        path = ROOT / ".github" / "actions" / "verify" / "action.yml"
        text = path.read_text()
        self.assertIn("using: composite", text)
        self.assertIn("gisel lint --corpus", text)
        self.assertIn("gisel cases --corpus", text)
        self.assertIn("gisel-ab suite check", text)


class PreCommitHook(unittest.TestCase):
    def test_hook_is_declared_in_gisel(self):
        path = GIVEN / ".pre-commit-hooks.yaml"
        if not path.is_file():
            self.skipTest("gisel checkout not present")
        text = path.read_text()
        self.assertIn("id: gisel-lint", text)
        self.assertIn("entry: gisel lint", text)
        self.assertIn("files: '\\.gisel$'", text)


if __name__ == "__main__":
    unittest.main()
