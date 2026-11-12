"""Negative controls must distinguish blind, caught, and input error."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify(rc):
    proc = subprocess.run(
        ["bash", "-c",
         'source "$1/env.sh"; classify_negative_rc "$2" "control"',
         "_", str(ROOT), str(rc)],
        capture_output=True, text=True)
    return proc.returncode, proc.stderr


class NegativeRC(unittest.TestCase):
    def test_zero_is_blind(self):
        rc, err = classify(0)
        self.assertEqual(rc, 1, err)
        self.assertIn("control blind", err)

    def test_one_is_caught(self):
        rc, err = classify(1)
        self.assertEqual(rc, 0, err)
        self.assertIn("caught", err)

    def test_two_is_input_error(self):
        rc, err = classify(2)
        self.assertEqual(rc, 2, err)
        self.assertIn("input error", err)
        self.assertNotIn("control: caught", err)

    def test_an_unexpected_status_is_not_caught(self):
        for code in (3, 127, 130):
            with self.subTest(code=code):
                rc, err = classify(code)
                self.assertEqual(rc, 2, err)
                self.assertIn("input error", err)
                self.assertNotIn("control: caught", err)


if __name__ == "__main__":
    unittest.main()
