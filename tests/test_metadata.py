import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_plugin_can_be_installed_from_repository_root(self):
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "valvesky.lockin")
        for kind, entry in (("service", "service"), ("bar-widget", "barWidget")):
            self.assertIn(kind, manifest["kinds"])
            self.assertTrue((ROOT / manifest["entryPoints"][entry]).is_file())

    def test_portuguese_covers_english_catalog(self):
        english = json.loads((ROOT / "i18n/en.json").read_text())
        portuguese = json.loads((ROOT / "i18n/pt.json").read_text())
        self.assertEqual(set(english), set(portuguese))
        for key in english:
            if isinstance(english[key], str):
                self.assertIsInstance(portuguese[key], str)
                for placeholder in ("%1", "%2"):
                    self.assertEqual(english[key].count(placeholder), portuguese[key].count(placeholder), key)

    def test_screenshots_are_reproducible_examples(self):
        for name in ("deepwork", "focus", "pomodoro", "break"):
            self.assertTrue((ROOT / "assets" / f"{name}.png").is_file())


if __name__ == "__main__":
    unittest.main()
