import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class WizardAssetsTests(unittest.TestCase):
    def test_static_assets_exist_and_are_local(self):
        web = ROOT / "telegram_bridge" / "web"
        for name in ("index.html", "app.css", "app.js"):
            self.assertTrue((web / name).is_file(), name)
        html = (web / "index.html").read_text()
        js = (web / "app.js").read_text()
        self.assertIn("{{NONCE}}", html)
        self.assertIn("{{CSRF}}", html)
        self.assertIn('"X-CSRF-Token"', js)
        self.assertNotIn("https://", html + js)
        self.assertEqual(html.count('data-step="'), 4)
        self.assertEqual(html.count('data-page="'), 4)
        self.assertIn("prefers-color-scheme:dark", (web / "app.css").read_text())
        self.assertIn("focus-visible", (web / "app.css").read_text())


if __name__ == "__main__":
    unittest.main()
