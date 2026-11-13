"""The U leg must build from the same tree/build the contract names.

The leg used to rely on ``AB_TREE``/``AB_BUILD`` defaults while the contract
recorded the ``--tree`` given to the G leg, so the evidence could name one
build and use another.  There is exactly one constructor now
(``vertical.leg_command``); this test pins that the command carries both roots
and that the script hands them to the builder.
"""

import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "e2e" / "run-u-end-to-end.sh"

from gisel_ab import vertical  # noqa: E402


class ULegProvenance(unittest.TestCase):
    def test_leg_command_names_tree_and_build(self):
        cmd = vertical.leg_command(
            "e2e/run-u-end-to-end.sh", "x86", "/q.jsonl", "/out",
            "--allow-unanswerable", "0", tree="/t", build="/b")
        self.assertEqual(cmd[0], ROOT / "scripts" / "e2e" / "run-u-end-to-end.sh")
        self.assertEqual(cmd[cmd.index("--tree") + 1], "/t")
        self.assertEqual(cmd[cmd.index("--build") + 1], "/b")

    def test_the_builder_receives_tree_and_build(self):
        text = SCRIPT.read_text()
        self.assertIn('"$BUILDER" "$TREE" "$BUILD"', text)
        self.assertIn('require_roots "$TREE" "$BUILD"', text)

    def test_the_negative_leg_does_not_reuse_defaults(self):
        text = (ROOT / "scripts" / "negative" / "run-g-negative.sh").read_text()
        self.assertIn('require_roots "$TREE" "$BUILD"', text)
        self.assertIn('"$SCRIPT" "$TREE" "$BUILD"', text)


if __name__ == "__main__":
    unittest.main()
