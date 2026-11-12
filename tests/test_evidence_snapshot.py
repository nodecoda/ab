"""The three L4 answer sets must name the source they were produced from."""

import hashlib
import json
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GISEL = Path(os.environ.get("GISEL_SRC") or ROOT.parent / "gisel")
TARGETS = ("x86", "aarch64", "riscv")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@unittest.skipUnless(GISEL.is_dir(), "gisel checkout is not next to ab")
class Snapshot(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / "EVIDENCE.json").read_text())
        self.entries = {e["id"]: e for e in self.manifest["entries"]}

    def test_every_l4_answer_set_pins_its_source(self):
        seen = set()
        for target in TARGETS:
            for direction in ("G", "U"):
                entry = self.entries["%s/%s" % (direction, target)]
                seen.add(entry["id"])
                with self.subTest(entry=entry["id"]):
                    snap = entry["snapshot"]
                    self.assertEqual(snap["corpus_sha256"],
                                     sha(GISEL / "tests" / "corpus" / snap["corpus"]))
                    self.assertEqual(snap["inc_sha256"],
                                     sha(GISEL / "tests" / "artifacts" / snap["inc"]))
                    self.assertEqual(snap["features_sha256"],
                                     sha(GISEL / "tests" / "cases" / snap["features"]))
        self.assertEqual(seen, {"%s/%s" % (d, t) for t in TARGETS for d in "GU"})

    def test_snapshot_matches_the_vertical_contract(self):
        for target in TARGETS:
            with self.subTest(target=target):
                contract = json.loads(
                    (ROOT / "data" / ("%s-contract.json" % target)).read_text())
                for direction in ("G", "U"):
                    snap = self.entries["%s/%s" % (direction, target)]["snapshot"]
                    self.assertEqual(snap["inc_sha256"],
                                     contract["snapshot"]["inc_sha256"])
                    self.assertEqual(snap["corpus_sha256"],
                                     contract["snapshot"]["corpus_sha256"])


if __name__ == "__main__":
    unittest.main()
