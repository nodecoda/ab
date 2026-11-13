import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


from gisel_ab.l0 import g_attribution as ga  # noqa: E402
from gisel_ab.l0 import u_attribution as ua  # noqa: E402


class AttributionKeysTest(unittest.TestCase):
    def test_wildcard_pointer_query_joins_a_concrete_runner_key(self):
        row = {"config": "C1", "name": "G_LOAD", "types": ["s16", "p0:*"],
               "mem": ["s15", 1], "imms": []}
        keys = ua._expand_pointer_widths(ua.query_key(row))
        concrete = ua.query_key({"config": "C1", "name": "G_LOAD",
                                 "types": ["s16", "p0:64"],
                                 "mem": ["s15", 1, "NotAtomic", "NotAtomic"],
                                 "imms": []})
        self.assertIn(concrete, keys)

    def test_g_attribution_uses_the_wildcard_variants(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "queries.jsonl").write_text(json.dumps({
                "config": "C1", "name": "G_LOAD", "types": ["s16", "p0:*"],
                "mem": ["s15", 1], "imms": [], "ruleset": "X_G_LOAD",
                "rule": 3}) + "\n")
            (d / "expect.json").write_text(json.dumps({
                "opcodes": ["G_LOAD"]}))
            (d / "diff.json").write_text(json.dumps({
                "disagree": 1,
                "first_details": [{
                    "class": "action",
                    "key_fields": {"config": "C1", "name": "G_LOAD",
                                   "types": ["s16", "p0:64"],
                                   "mem": ["s15", 1, "NotAtomic",
                                           "NotAtomic"],
                                   "imms": []},
                }],
            }))
            out = d / "attribution.json"
            rc = ga.main(["g-attribution.py", str(d / "diff.json"),
                          str(d / "queries.jsonl"), str(d / "expect.json"),
                          str(out)])
            self.assertEqual(rc, 0)
            report = json.loads(out.read_text())
            self.assertEqual(report["by_ruleset"], {"X_G_LOAD": 1})
            self.assertEqual(report["unknown_keys"], 0)


if __name__ == "__main__":
    unittest.main()
