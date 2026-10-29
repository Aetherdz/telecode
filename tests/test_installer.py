import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_installer_accepts_curl_bootstrap_flag_without_extra_args(self):
        text = (ROOT / "install.sh").read_text()
        self.assertIn('"--curl-bootstrap"', text)
        self.assertIn("github.com/Aetherdz/telecode.git", text)
        self.assertIn('! -d "$bootstrap_dir/repo/.git"', text)

    def test_curl_bootstrap_shows_logo_before_download_and_after_completion(self):
        text = (ROOT / "install.sh").read_text()
        bootstrap = text.split('if [[ "${1:-}" == "--curl-bootstrap" ]]; then', 1)[1].split("\nfi\n", 1)[0]
        self.assertEqual(bootstrap.count("  logo"), 2)
        self.assertLess(bootstrap.index("  logo"), bootstrap.index("Downloading TeleCode source"))
        self.assertLess(bootstrap.index("[100%] Download complete."), bootstrap.rindex("  logo"))
        self.assertIn("Starting TeleCode setup...", bootstrap)
    def test_bootstrap_is_self_contained_and_help_is_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "PATH": f"{home / '.local/bin'}:{env['PATH']}",
            })
            run = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--bootstrap"],
                cwd=ROOT, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr)
            app = home / "data/telegram-bridge"
            self.assertTrue((app / "adapters/__init__.py").is_file())
            self.assertTrue((app / "config/opencode.example.json").is_file())
            self.assertTrue((app / ".env.example").is_file())
            self.assertTrue((app / "get_telegram_id.py").is_file())
            self.assertEqual((home / "config/telegram-bridge/telegram.env").stat().st_mode & 0o777, 0o600)
            help_run = subprocess.run(
                [str(home / ".local/bin/telecode"), "help"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(help_run.returncode, 0, help_run.stderr)
            self.assertIn("@BotFather", help_run.stdout)
            self.assertIn("@Getmyid_bot", help_run.stdout)
            self.assertTrue((home / "config/telegram-bridge/files").is_dir())
            update_run = subprocess.run(
                [str(home / ".local/bin/telecode"), "update"],
                env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(update_run.returncode, 2)
            self.assertIn("./install.sh --update", update_run.stderr)

    def test_source_update_refreshes_runtime_without_overwriting_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({
                "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
            })
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"],
                           cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            config = home / "config/telegram-bridge/telegram.env"
            config.write_text("TG_BOT_TOKEN=local-placeholder\nTG_CHAT_ID=123\n")
            run = subprocess.run(["bash", str(ROOT / "install.sh"), "--update"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("Installed to", run.stdout)
            self.assertEqual(config.read_text(), "TG_BOT_TOKEN=local-placeholder\nTG_CHAT_ID=123\n")
            self.assertTrue((home / "data/telegram-bridge/config/opencode.example.json").is_file())

    def test_setup_is_reentrant_and_help_does_not_require_telegram(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({
                "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "PATH": f"{home / '.local/bin'}:{env['PATH']}",
            })
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"],
                           cwd=ROOT, env=env, capture_output=True, text=True, check=True)
            app = home / "data/telegram-bridge"
            run = subprocess.run(["bash", str(app / "install.sh"), "--bootstrap"],
                                 env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            # Help must be local, and never attempt API access.
            help_run = subprocess.run([str(home / ".local/bin/telecode"), "help"],
                                      env=env, capture_output=True, text=True, check=False)
            self.assertEqual(help_run.returncode, 0, help_run.stderr)
            self.assertIn("Never send your bot token", help_run.stdout)

    def test_launcher_quotes_paths_with_shell_metacharacters(self):
        with tempfile.TemporaryDirectory(prefix="tele code ' $(nope) ") as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({
                "HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "PATH": f"{home / '.local/bin'}:{env['PATH']}",
            })
            run = subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"],
                                 cwd=ROOT, env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 0, run.stderr)
            launcher = home / ".local/bin/telecode"
            syntax = subprocess.run(["bash", "-n", str(launcher)], capture_output=True, text=True)
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            help_run = subprocess.run([str(launcher), "help"], env=env,
                                      capture_output=True, text=True, check=False)
            self.assertEqual(help_run.returncode, 0, help_run.stderr)

    def test_invalid_credentials_block_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                        "XDG_DATA_HOME": str(home / "data")})
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"], cwd=ROOT,
                           env=env, capture_output=True, text=True, check=True)
            run = subprocess.run(["bash", str(home / "data/telegram-bridge/install.sh"), "--enable"],
                                 env=env, capture_output=True, text=True, check=False)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn("valid TG_BOT_TOKEN", run.stderr)

    def test_installed_update_refuses_before_rewriting_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                        "XDG_DATA_HOME": str(home / "data")})
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"], cwd=ROOT,
                           env=env, capture_output=True, text=True, check=True)
            app_install = home / "data/telegram-bridge/install.sh"
            before = app_install.read_bytes()
            run = subprocess.run(["bash", str(app_install), "--update"], env=env,
                                 capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(app_install.read_bytes(), before)

    def test_enable_rejects_systemd_paths_with_spaces_before_systemctl(self):
        with tempfile.TemporaryDirectory(prefix="tele code ") as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                        "XDG_DATA_HOME": str(home / "data")})
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"], cwd=ROOT,
                           env=env, capture_output=True, text=True, check=True)
            config = home / "config/telegram-bridge/telegram.env"
            config.write_text("TG_BOT_TOKEN=12345:" + "a" * 25 + "\nTG_CHAT_ID=123\n")
            run = subprocess.run(["bash", str(home / "data/telegram-bridge/install.sh"), "--enable"],
                                 env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 2)
            self.assertIn("does not support whitespace", run.stderr)

    def test_enable_without_systemctl_reports_foreground_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            env = os.environ.copy()
            env.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "config"),
                        "XDG_DATA_HOME": str(home / "data")})
            subprocess.run(["bash", str(ROOT / "install.sh"), "--bootstrap"], cwd=ROOT,
                           env=env, capture_output=True, text=True, check=True)
            config = home / "config/telegram-bridge/telegram.env"
            config.write_text("TG_BOT_TOKEN=12345:" + "a" * 25 + "\nTG_CHAT_ID=123\n")
            shim = home / "bin"
            shim.mkdir()
            for name in ("bash", "python3", "grep", "sed", "mktemp", "chmod", "mv",
                         "mkdir", "install", "dirname", "basename", "realpath", "cat", "rm"):
                target = shutil.which(name)
                if target:
                    os.symlink(target, shim / name)
            env["PATH"] = str(shim)
            run = subprocess.run(["bash", str(home / "data/telegram-bridge/install.sh"), "--enable"],
                                 env=env, capture_output=True, text=True, check=False)
            self.assertEqual(run.returncode, 3, run.stderr)
            self.assertIn("systemd user services are not available", run.stderr)
            self.assertIn("telecode listen", run.stderr)


if __name__ == "__main__":
    unittest.main()
