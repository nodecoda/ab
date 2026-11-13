"""u-attribution joins diff keys back to the query file.

The runners echo LLT, which has no float kind: `f32` comes back as `s32` and
`bf16` as `s16`.  The join must collapse both the same way, or a witness for a
float-typed rule looks like a key nobody asked about and the negative control
reports `unknown_keys` instead of blaming the injected ruleset.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = ROOT.parent / "gisel"
sys.path.insert(0, str(GISEL))

from gisel_ab.l0 import u_attribution  # noqa: E402

query_key = u_attribution.query_key


def row(config, name, types, mem=None, imms=()):
    return {"config": config, "name": name, "types": types,
            "mem": mem, "imms": list(imms)}


class RunnerTypeCollapse(unittest.TestCase):
    def test_bf16_scalar_and_vector_match_runner_echo(self):
        asked = row("C0", "G_ABS", ["v16bf16"],
                    ["v16bf16", 32, "NotAtomic", "NotAtomic"])
        echoed = row("C0", "G_ABS", ["v16s16"],
                     ["v16s16", 32, "NotAtomic", "NotAtomic"])
        self.assertEqual(query_key(asked), query_key(echoed))

        scalar = row("C0", "G_ABS", ["bf16"],
                     ["bf16", 16, "NotAtomic", "NotAtomic"])
        scalar_echo = row("C0", "G_ABS", ["s16"],
                          ["s16", 16, "NotAtomic", "NotAtomic"])
        self.assertEqual(query_key(scalar), query_key(scalar_echo))

    def test_float_scalar_matches_runner_echo(self):
        asked = row("C0", "G_FADD", ["f32"])
        echoed = row("C0", "G_FADD", ["s32"])
        self.assertEqual(query_key(asked), query_key(echoed))

    def test_pointer_and_scalar_are_not_rewritten(self):
        key = query_key(row("C0", "G_PTR_ADD", ["p0:64", "s64"]))
        self.assertEqual(key[2], (("pointer", 0, 64), ("scalar", 64)))


if __name__ == "__main__":
    unittest.main()
