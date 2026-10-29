import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class SiteTests(unittest.TestCase):
    def test_language_menu_has_requested_languages_and_persisted_options(self):
        html = (ROOT / "index.html").read_text()
        js = (ROOT / "assets/site.js").read_text()
        self.assertIn('data-language="ar"', html)
        self.assertIn('data-language="en"', html)
        self.assertIn('data-language="fr"', html)
        self.assertIn("const supportedLanguages = ['en', 'ar', 'fr'];", js)
        for language in ("en", "ar", "fr"):
            self.assertIn(f"{language}: {{", js)
        self.assertIn("pageTitle: 'TeleCode — vos sessions de code", js)
        self.assertIn("copySuccess: 'Commande copiée.'", js)
        self.assertIn('class="language-chevron"', html)
        self.assertIn("querySelector('[data-language][aria-pressed=\"true\"]')?.focus()", js)

    def test_language_control_has_mobile_target_size_and_visible_dropdown(self):
        css = (ROOT / "assets/site.css").read_text()
        self.assertIn(".language-toggle { display: inline-flex; min-width: 68px; min-height: 44px", css)
        self.assertIn(".language-options { position: absolute", css)
        self.assertIn(".language-toggle[aria-expanded=\"true\"] .language-chevron", css)

    def test_floating_bar_uses_requested_links_without_whatsapp_or_audio(self):
        html = (ROOT / "index.html").read_text()
        self.assertIn('class="floating-tools"', html)
        self.assertIn('href="https://github.com/Aetherdz"', html)
        self.assertIn('href="https://www.linkedin.com/in/aether-dz"', html)
        self.assertIn('href="https://t.me/PP9PS"', html)
        self.assertNotIn('wa.me/', html)
        self.assertNotIn('whatsapp', html.lower())
        self.assertNotIn('audio', html.lower())
        self.assertIn(".floating-tools { position: fixed", (ROOT / "assets/site.css").read_text())

    def test_mobile_install_panel_stacks_long_command_and_copy_control(self):
        css = (ROOT / "assets/site.css").read_text()
        self.assertRegex(css, r"@media \(max-width: 560px\)[\s\S]*?\.install-panel > \.install-command\s*\{[^}]*flex-direction:\s*column")
        self.assertIn("overflow-wrap: anywhere", css)

    def test_bootstrap_progress_finishes_at_100_before_install(self):
        script = (ROOT / "install.sh").read_text()
        self.assertIn("'[100%] Download complete.'", script)
        self.assertIn('git clone --progress --depth 1', script)
        self.assertLess(script.index("'[100%] Download complete.'"), script.index('exec bash "$bootstrap_dir/repo/install.sh"'))

    def test_bootstrap_logo_is_defined_before_early_mode(self):
        script = (ROOT / "install.sh").read_text()
        self.assertLess(script.index("logo() {"), script.index('if [[ "${1:-}" == "--curl-bootstrap" ]]'))


if __name__ == "__main__":
    unittest.main()
