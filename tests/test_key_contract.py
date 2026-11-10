"""The query key is the contract between gisel and ab.

`gisel.jsonl` is the only gisel module ab imports.  This test pins its
normalisation with frozen reprs, so a change in gisel's key construction shows
up here as well as in gisel's own tests.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = ROOT.parent / "gisel"
sys.path.insert(0, str(GISEL))
sys.path.insert(0, str(ROOT))

from gisel import jsonl as J  # noqa: E402
import diff  # noqa: E402


FIXTURES = [
    ({"config": "C0", "name": "G_ADD", "types": ["s32"], "mem": None,
      "imms": []},
     "('C0', 'G_ADD', (('scalar', 32),), None, ())"),
    ({"config": "C0", "name": "G_LOAD", "types": ["s64"],
      "mem": ["s64", 8]},
     "('C0', 'G_LOAD', (('scalar', 64),), "
     "(('scalar', 64), 8, 'NotAtomic', 'NotAtomic'), ())"),
    ({"config": "C1", "name": "G_PTR_ADD",
      "types": ["p0:*", "p0:*", "s64"], "mem": None},
     "('C1', 'G_PTR_ADD', (('pointer', 0, '*'), ('pointer', 0, '*'), "
     "('scalar', 64)), None, ())"),
    ({"config": "C0", "name": "G_ATOMIC_CMPXCHG", "types": ["s32"],
      "mem": ["s32", 4, "monotonic", "monotonic"], "imms": [0]},
     "('C0', 'G_ATOMIC_CMPXCHG', (('scalar', 32),), "
     "(('scalar', 32), 4, 'monotonic', 'monotonic'), (0,))"),
    ({"config": "C0", "name": "G_CONSTANT", "types": ["s32"]},
     "('C0', 'G_CONSTANT', (('scalar', 32),), None, ())"),
]


class KeyContract(unittest.TestCase):
    def test_frozen_keys(self):
        for query, expected in FIXTURES:
            with self.subTest(query=query["name"]):
                self.assertEqual(repr(J.key(query)), expected)

    def test_ab_uses_the_same_key_function(self):
        # diff.py's comparison keys and the reader must be the same function:
        # a second implementation is how the two sides silently diverge.
        self.assertIs(diff.J.key, J.key)
        self.assertIs(diff.J.load, J.load)

    def test_llt_spelling_is_core_ir(self):
        self.assertEqual(J.llt_text(("scalar", 32)), "s32")
        self.assertEqual(J.llt_text(("pointer", 0, "*")), "p0:*")
        self.assertEqual(J.llt_text(("vector", 4, False, ("scalar", 32))),
                         "v4s32")


if __name__ == "__main__":
    unittest.main()
