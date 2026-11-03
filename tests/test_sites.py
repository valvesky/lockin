import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import sites
from sites import DEFAULT_SITES, Invalid, blocked, render, validate, write

HOSTS = (b"# Generated with hBlock\n127.0.0.1 localhost\n::1 localhost\n"
         b"# BEGIN BLOCKLIST\n0.0.0.0 ads.example\n# END BLOCKLIST\n")


class SitesTests(unittest.TestCase):
    def test_defaults_cover_the_usual_feeds(self):
        validate(DEFAULT_SITES)
        for domain in ("x.com", "twitter.com", "www.youtube.com", "www.reddit.com",
                       "www.pinterest.com", "www.instagram.com", "www.tiktok.com", "www.facebook.com"):
            self.assertIn(domain, DEFAULT_SITES)
        self.assertNotIn("music.youtube.com", DEFAULT_SITES)

    def test_block_appends_both_families_and_unblock_restores_every_byte(self):
        on = render(HOSTS, ["x.com", "www.reddit.com"])
        self.assertTrue(on.startswith(HOSTS))
        self.assertIn(b"\n0.0.0.0 x.com\n:: x.com\n", on)
        self.assertTrue(blocked(on))
        self.assertFalse(blocked(HOSTS))
        self.assertEqual(render(on, ["x.com", "www.reddit.com"]), on)
        self.assertEqual(render(on), HOSTS)
        self.assertEqual(render(HOSTS), HOSTS)

    def test_missing_trailing_newline_and_truncated_block(self):
        self.assertEqual(render(b"127.0.0.1 localhost", ["x.com"]).split(b"\n")[:2],
                         [b"127.0.0.1 localhost", b"# BEGIN LOCK-IN (focus session; removed automatically)"])
        self.assertEqual(render(HOSTS + b"# BEGIN LOCK-IN\n0.0.0.0 x.com\n"), HOSTS)

    def test_only_plain_hostnames_reach_the_hosts_file(self):
        for bad in ([], ["localhost"], ["X.com"], ["x.com\n127.0.0.1 evil"], ["x.com evil.com"],
                    ["-x.com"], ["1.2.3.4"], ["x.com#"], ["a" * 300 + ".com"], [f"s{n}.example.com" for n in range(600)]):
            with self.assertRaises(Invalid):
                validate(bad)

    def test_write_replaces_atomically_and_keeps_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hosts"
            path.write_bytes(HOSTS)
            os.chmod(path, 0o644)
            write(str(path), ["x.com"])
            self.assertTrue(blocked(path.read_bytes()))
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)
            write(str(path), None)
            self.assertEqual(path.read_bytes(), HOSTS)
            self.assertEqual(list(Path(directory).glob(".hosts-lockin-*")), [])
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaisesRegex(Invalid, "hosts_is_symlink"):
                write(str(link), ["x.com"])

    def test_helper_rejects_other_commands(self):
        result = subprocess.run([sys.executable, str(ROOT / "src/sites.py"), "--hosts", "/tmp/x"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_setup_rule_names_only_block_and_unblock(self):
        script = (ROOT / "src/site-block-setup").read_text()
        self.assertIn("NOPASSWD: %s block, %s unblock", script)
        self.assertIn("visudo -cqf", script)
        self.assertTrue(os.access(ROOT / "src/site-block-setup", os.X_OK))
        self.assertEqual(sites.HELPER, "/usr/local/libexec/lockin-sites")


if __name__ == "__main__":
    unittest.main()
