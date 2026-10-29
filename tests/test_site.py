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
        self.assertIn("if (options) options.hidden = false;", js)

    def test_language_control_has_mobile_target_size_and_visible_dropdown(self):
        css = (ROOT / "assets/site.css").read_text()
        self.assertIn(".language-toggle { display: inline-flex; min-width: 68px; min-height: 44px", css)
        self.assertIn(".language-options { position: absolute", css)
        self.assertIn(".language-options[hidden] { display: none; }", css)
        self.assertIn(".language-options[hidden] { display: none; }", css)
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

    def test_floating_tools_touch_targets_meet_44px_minimum(self):
        css = (ROOT / "assets/site.css").read_text()
        self.assertIn(".floating-icon { width: 40px; height: 40px; }", css)
        self.assertIn(".floating-icon { width: 36px; height: 44px; }", css)
        self.assertIn(".floating-tools .language-toggle { min-width: 64px; min-height: 44px; }", css)
        self.assertIn(".floating-tools .language-toggle { min-width: 74px; min-height: 44px;", css)
        self.assertIn("inset-inline-end: 0;", css)

    def test_language_menu_keeps_focus_on_toggle_when_opened(self):
        js = (ROOT / "assets/site.js").read_text()
        self.assertIn("closeLanguageMenus(true);", js)

    def test_language_toggle_can_close_open_menu_by_clicking_chevron(self):
        js = (ROOT / "assets/site.js").read_text()
        self.assertIn("const open = button.getAttribute('aria-expanded') !== 'true';", js)
        self.assertIn("if (options) options.hidden = false;", js)
        self.assertIn("button.setAttribute('aria-expanded', 'true');", js)

    def test_theme_toggle_renders_contextual_sun_moon_icon_and_label(self):
        js = (ROOT / "assets/site.js").read_text()
        self.assertIn("<circle cx=\"12\" cy=\"12\" r=\"4\"></circle>", js)
        self.assertIn("20.5 15.5A8.5 8.5", js)
        self.assertIn("button.title = messages[language]", js)

    def test_mobile_install_panel_stacks_long_command_and_copy_control(self):
        css = (ROOT / "assets/site.css").read_text()
        self.assertRegex(css, r"@media \(max-width: 560px\)[\s\S]*?\.install-panel > \.install-command\s*\{[^}]*grid-template-columns")
        self.assertIn("overflow-wrap: anywhere", css)

    def test_install_command_and_copy_action_have_clear_visual_grouping(self):
        html = (ROOT / "index.html").read_text()
        css = (ROOT / "assets/site.css").read_text()
        self.assertIn('class="copy-button"', html)
        self.assertIn('<svg aria-hidden="true" viewBox="0 0 24 24"><rect x="8" y="8"', html)
        self.assertIn(".install-panel > .install-command { display: grid;", css)
        self.assertIn("background: color-mix(in srgb, var(--telegram) 9%, var(--panel))", css)
        self.assertIn(".copy-button { display: inline-flex; min-width: 116px; min-height: 48px", css)
        self.assertIn(".copy-button:focus-visible", css)

    def test_bootstrap_progress_finishes_at_100_before_install(self):
        script = (ROOT / "install.sh").read_text()
        self.assertIn("'[100%] Download complete.'", script)
        self.assertIn('git clone --quiet --depth 1', script)
        self.assertIn("printf '\\r[%3d%%] [%-10s]'", script)
        self.assertLess(script.index("'[100%] Download complete.'"), script.index('exec bash "$bootstrap_dir/repo/install.sh"'))

    def test_bootstrap_logo_is_defined_before_early_mode(self):
        script = (ROOT / "install.sh").read_text()
        self.assertLess(script.index("logo() {"), script.index('if [[ "${1:-}" == "--curl-bootstrap" ]]'))

    def test_download_progress_bar_is_fixed_length_not_page_long(self):
        script = (ROOT / "install.sh").read_text()
        self.assertIn("local filled=$((progress / 10))", script)
        self.assertIn("[%-10s]", script)
        self.assertIn("show_download_progress 100", script)


if __name__ == "__main__":
    unittest.main()
