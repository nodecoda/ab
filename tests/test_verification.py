"""The post-tag record must name the frozen cohort, not a later tree."""

import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE.json"
VERIFICATION = ROOT / "VERIFICATION.json"


def git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args],
                          capture_output=True, text=True)


class VerificationRecord(unittest.TestCase):
    def setUp(self):
        self.assertTrue(VERIFICATION.is_file(), "VERIFICATION.json is missing")
        self.record = json.loads(VERIFICATION.read_text())
        self.manifest = json.loads(MANIFEST.read_text())

    def test_cohort_matches_the_manifest(self):
        self.assertEqual(self.record["cohort"], self.manifest["cohort"])
        self.assertTrue(self.record["cohort"].startswith("cohort-"))
        self.assertNotIn(" ", self.record["cohort"])

    def test_commits_are_the_manifest_commits(self):
        for name in ("gisel", "upstream_source"):
            self.assertEqual(self.record["commits"][name],
                             self.manifest["repos"][name], name)
        # `repos.ab` is the code commit before the manifest; the tag points at
        # the manifest commit itself, which is the commit verified above.
        self.assertEqual(self.record["commits"]["ab"],
                         self.record["manifest_commit"])

    def test_manifest_commit_is_the_latest_edit(self):
        # RELEASE.json is frozen after its manifest commit; a later edit must
        # move both fields or fail here.
        found = git("log", "-1", "--format=%H", "--", "RELEASE.json")
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertEqual(self.record["manifest_commit"], found.stdout.strip())

    def test_the_ab_tag_resolves_to_the_recorded_commit(self):
        tag = self.record["tag"]
        found = git("rev-parse", tag + "^{commit}")
        self.assertEqual(found.returncode, 0,
                         "tag %s is not fetched: %s" % (tag, found.stderr))
        self.assertEqual(found.stdout.strip(), self.record["commits"]["ab"])

    def test_the_superseded_tag_is_named(self):
        self.assertTrue(self.record["supersedes"].startswith("cohort-"))
        self.assertNotEqual(self.record["supersedes"], self.record["cohort"])
        self.assertTrue(self.record["supersedes_reason"])

    def test_every_ci_run_is_green_and_publish_is_absent(self):
        for name, item in self.record["ci"].items():
            if name == "publish":
                self.assertEqual(item["runs"], 0)
                continue
            self.assertEqual(item["conclusion"], "success", name)

    def test_gates_cover_the_manifest(self):
        recorded = {gate["command"] for gate in self.record["gates"]}
        for command in self.manifest["gates"]:
            self.assertIn(command, recorded)
        for gate in self.record["gates"]:
            self.assertEqual(gate["rc"], 0, gate["command"])


if __name__ == "__main__":
    unittest.main()
