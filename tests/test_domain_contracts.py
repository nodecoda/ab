"""The four domain entry points must agree on the config sets they cover.

`run-domain.sh` reads `data/domain.json`; x86, AArch64 and RISC-V keep their
own scripts with their own pins.  Consolidating them needs a full 8.4M-query
rerun, so this round only locks the drift: a features file that grows a
config, or a `data/domain.json` entry with no runner, fails here instead of
surfacing as a surprise in a multi-hour run.
"""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GISEL = Path(__file__).resolve().parents[2] / "gisel"
FEATURES = GISEL / "tests" / "cases"
DOMAIN = ROOT / "data" / "domain.json"
GENERIC = {"m68k", "ppc", "arm", "mips", "wasm", "spirv"}


def configs(script: str):
    text = (ROOT / script).read_text()
    match = re.search(r"^CONFIGS=\$\{CONFIGS:-([^}]*)\}", text, re.M)
    return match.group(1).split() if match else []


def feature_keys(name: str):
    filename = "features.json" if name == "aarch64" else name + "-features.json"
    return list(json.loads((FEATURES / filename).read_text()))


def pin(script: str, name: str):
    text = (ROOT / script).read_text()
    match = re.search(r"^%s=(.*)$" % re.escape(name), text, re.M)
    return match.group(1).strip() if match else None


def plan(target: str):
    r = subprocess.run(
        ["bash", str(ROOT / "run-domain.sh"), target, "--plan"],
        cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(r.stdout)


class DomainEntryPoints(unittest.TestCase):
    def test_aarch64_configs_match_the_features_file(self):
        self.assertEqual(configs("run-aarch64-domain.sh"),
                         feature_keys("aarch64"))

    def test_riscv_configs_match_the_features_file(self):
        self.assertEqual(configs("run-riscv-domain.sh"),
                         feature_keys("riscv"))

    def test_riscv_unanswerable_map_covers_every_config(self):
        raw = pin("run-riscv-domain.sh", "EXPECTED_UNANSWERABLE_MAP")
        self.assertIsNotNone(raw)
        match = re.search(r"'(\{.*\})'", raw)
        self.assertIsNotNone(match, raw)
        mapping = json.loads(match.group(1))
        self.assertEqual(set(mapping), set(feature_keys("riscv")))

    def test_x86_uses_every_declared_config(self):
        text = (ROOT / "run-x86-domain.sh").read_text()
        self.assertIsNotNone(pin("run-x86-domain.sh", "EXPECTED_QUERIES"))
        self.assertNotIn("--config", text,
                         "x86 domain asks every config; a --config pin would "
                         "silently narrow it")

    def test_generic_targets_have_a_section_and_a_runner(self):
        domain = json.loads(DOMAIN.read_text())["targets"]
        self.assertEqual(set(domain), GENERIC)
        for name, doc in domain.items():
            self.assertEqual(set(doc["configs"]), set(feature_keys(name)), name)
            target = json.loads((ROOT / "targets" / (name + ".json")).read_text())
            runner = target.get("domain") or "run-domain.sh"
            self.assertTrue((ROOT / runner).exists(), name)

    def test_plan_names_every_config_without_a_tree(self):
        for name in ("x86", "aarch64", "riscv", "mips"):
            with self.subTest(target=name):
                doc = plan(name)
                self.assertEqual(set(doc["configs"]), set(feature_keys(name)))
                self.assertEqual(doc["target"], name)
                spec = json.loads(
                    (ROOT / "targets" / (name + ".json")).read_text())
                self.assertEqual(doc["runner"], spec.get("domain") or "run-domain.sh")

    def test_plan_keeps_the_special_contracts(self):
        x86 = plan("x86")
        self.assertEqual(x86["queries"], {"mode": "total", "value": 91340})
        self.assertEqual(x86["unanswerable"],
                         {"mode": "total", "value": 648})
        aarch64 = plan("aarch64")
        self.assertEqual(aarch64["queries"]["mode"], "per_config")
        self.assertEqual(set(aarch64["queries"]["value"].values()), {936960})
        self.assertEqual(set(aarch64["unanswerable"]["value"].values()),
                         {39056})
        riscv = plan("riscv")
        self.assertEqual(riscv["unanswerable"]["mode"], "map")
        self.assertEqual(set(riscv["unanswerable"]["value"]),
                         set(feature_keys("riscv")))

    def test_plan_generic_matches_the_domain_contract(self):
        domain = json.loads(DOMAIN.read_text())["targets"]
        for name in GENERIC:
            with self.subTest(target=name):
                doc = plan(name)
                self.assertEqual(doc["queries"]["value"], domain[name]["configs"])
                self.assertEqual(doc["unanswerable"]["value"],
                                 domain[name].get("unanswerable") or {})

    def test_the_special_scripts_are_the_only_exceptions(self):
        domain = json.loads(DOMAIN.read_text())["targets"]
        special = {"x86", "aarch64", "riscv"}
        self.assertFalse(special & set(domain),
                         "a special target must not also be generic")


if __name__ == "__main__":
    unittest.main()
