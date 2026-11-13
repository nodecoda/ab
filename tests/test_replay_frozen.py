"""Frozen-answer replay: the comparison rules, without a build tree."""

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    return importlib.import_module("gisel_ab.replay_frozen")


class Compare(unittest.TestCase):
    def test_equal_scalars_pass(self):
        replay = load()
        frozen = {"agree": 9, "disagree": 0, "ours": 9, "ref": 9}
        self.assertEqual(replay.compare(frozen, dict(frozen)), [])

    def test_a_changed_count_is_named(self):
        replay = load()
        frozen = {"agree": 9, "disagree": 0}
        bad = replay.compare(frozen, {"agree": 8, "disagree": 1})
        self.assertEqual(len(bad), 2)
        self.assertIn("agree=8, frozen 9", bad[0])

    def test_known_reference_assertions_are_replayed_exactly(self):
        replay = load()
        cmd = replay.diff_command({"ref_asserted": 9, "unanswerable": 1},
                                  Path("ref.jsonl"), Path("ours.jsonl"),
                                  Path("queries.jsonl"))
        self.assertIn("--queries", cmd)
        self.assertEqual(cmd[cmd.index("--queries") + 1], "queries.jsonl")
        self.assertIn("--allow-ref-asserts", cmd)
        self.assertEqual(cmd[cmd.index("--allow-ref-asserts") + 1], "9")
        self.assertIn("--expect-unanswerable", cmd)
        self.assertEqual(cmd[cmd.index("--expect-unanswerable") + 1], "1")

    def test_keys_the_frozen_entry_does_not_have_are_ignored(self):
        replay = load()
        self.assertEqual(replay.compare({"agree": 1}, {"agree": 1,
                                                       "answered_equal": 1}), [])


if __name__ == "__main__":
    unittest.main()
