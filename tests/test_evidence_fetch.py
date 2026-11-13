"""`evidence fetch`: one command from a release asset to a verifiable tree."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gisel_ab import evidence

TAG = "cohort-2026-11-14-r10"


def make_asset(server: Path, tag: str = TAG, members=None,
               corrupt_checksum: bool = False) -> Path:
    repo = server / "nodecoda" / "gisel-ab" / "releases" / "download" / tag
    repo.mkdir(parents=True, exist_ok=True)
    archive = repo / ("evidence-%s.tar.gz" % tag)
    payload = members if members is not None else {
        "EVIDENCE.json": json.dumps({"schema": 2, "entries": []}) + "\n",
        "evidence/readme.txt": "frozen\n",
    }
    with tarfile.open(archive, "w:gz") as tar:
        for name, text in payload.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if corrupt_checksum:
        digest = "0" * 64
    (repo / (archive.name + ".sha256")).write_text(
        "%s  %s\n" % (digest, archive.name))
    return repo


class Fetch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.server = self.root / "server"
        self.dest = self.root / "cache" / TAG

    def fetch(self, **kwargs):
        return evidence.fetch_evidence(
            TAG, self.dest, base="file://" + str(self.server),
            repo="nodecoda/gisel-ab", **kwargs)

    def test_it_unpacks_the_asset(self):
        make_asset(self.server)
        dest = self.fetch()
        self.assertEqual(dest, self.dest)
        self.assertTrue((dest / "EVIDENCE.json").is_file())
        self.assertEqual((dest / "evidence" / "readme.txt").read_text(),
                         "frozen\n")
        self.assertTrue((dest / ".fetched").is_file())

    def test_the_cache_is_reused_without_network(self):
        make_asset(self.server)
        self.fetch()
        import shutil
        shutil.rmtree(self.server)
        self.fetch()  # would raise FileNotFoundError if it downloaded again

    def test_force_refetches(self):
        make_asset(self.server)
        self.fetch()
        (self.dest / "evidence" / "readme.txt").unlink()
        self.fetch(force=True)
        self.assertTrue((self.dest / "evidence" / "readme.txt").is_file())

    def test_a_bad_checksum_is_refused(self):
        make_asset(self.server, corrupt_checksum=True)
        with self.assertRaises(ValueError) as caught:
            self.fetch()
        self.assertIn("sha256", str(caught.exception))
        self.assertFalse((self.dest / "EVIDENCE.json").exists())

    def test_a_traversal_member_is_refused(self):
        make_asset(self.server, members={
            "EVIDENCE.json": "{}\n",
            "../escaped.txt": "no\n",
        })
        with self.assertRaises(ValueError) as caught:
            self.fetch()
        self.assertIn("unsafe path", str(caught.exception))
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_an_asset_without_a_manifest_is_refused(self):
        make_asset(self.server, members={"evidence/readme.txt": "x\n"})
        with self.assertRaises(ValueError) as caught:
            self.fetch()
        self.assertIn("EVIDENCE.json", str(caught.exception))


class Defaults(unittest.TestCase):
    def test_manifest_follows_the_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GISEL_AB_EVIDENCE": tmp}):
                self.assertEqual(evidence.default_manifest(),
                                 Path(tmp) / "EVIDENCE.json")

    def test_missing_manifest_suggests_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GISEL_AB_EVIDENCE": tmp}):
                err = io.StringIO()
                with contextlib.redirect_stderr(err):
                    rc = evidence.main(["verify", "--frozen"])
        self.assertEqual(rc, 2)
        self.assertIn("evidence fetch", err.getvalue())

    def test_tag_defaults_to_the_checkout_cohort(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "RELEASE.json"
            manifest.write_text(json.dumps({"cohort": TAG}))
            with mock.patch.object(evidence, "AB", Path(tmp)):
                self.assertEqual(evidence.default_tag(), TAG)


if __name__ == "__main__":
    unittest.main()
