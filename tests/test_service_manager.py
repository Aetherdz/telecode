import os
import pathlib
import plistlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import service_manager


class ServiceManagerTests(unittest.TestCase):
    def test_windows_crlf_credentials_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = pathlib.Path(tmp)
            (config / "telegram.env").write_bytes(
                b"TG_BOT_TOKEN=12345:FAKE_TOKEN_NOT_VALID\r\nTG_CHAT_ID=1\r\n")
            with patch.dict(os.environ, {"TELEGRAM_BRIDGE_HOME": str(config)}):
                service_manager._check_credentials()

    def test_windows_install_creates_schtasks_task_with_environment_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            config = root / "runtime"
            app = root / "app"
            config.mkdir()
            app.mkdir()
            (config / "telegram.env").write_text("TG_BOT_TOKEN=12345:FAKE_TOKEN_NOT_VALID\nTG_CHAT_ID=1\n")
            (app / "telegram-bridge.py").write_text("# fake entrypoint\n")
            with patch.dict(os.environ, {"TELEGRAM_BRIDGE_HOME": str(config), "TELECODE_SERVICE_APP_DIR": str(app)}), \
                 patch.object(service_manager.subprocess, "run") as run:
                service_manager._install_windows()
            argv = run.call_args.args[0]
            self.assertEqual(argv[:5], ["schtasks", "/Create", "/F", "/SC", "ONLOGON"])
            self.assertEqual(argv[argv.index("/TN") + 1], service_manager.TASK_NAME)
            wrapper = config / "telecode-listener.cmd"
            content = wrapper.read_text()
            self.assertIn(f'TELEGRAM_BRIDGE_HOME={config}', content)
            self.assertIn('listen', content)

    def test_windows_uninstall_deletes_task_and_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = pathlib.Path(tmp)
            wrapper = config / "telecode-listener.cmd"
            wrapper.touch()
            with patch.dict(os.environ, {"TELEGRAM_BRIDGE_HOME": str(config)}), \
                 patch.object(service_manager.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                service_manager._uninstall_windows()
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[1].args[0],
                             ["schtasks", "/Delete", "/F", "/TN", service_manager.TASK_NAME])
            self.assertFalse(wrapper.exists())

    def test_macos_plist_is_well_formed_and_contains_listener_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            app = root / "app"
            config = root / "config"
            app.mkdir()
            config.mkdir()
            plist_path = root / "LaunchAgents" / service_manager.PLIST_NAME
            with patch.dict(os.environ, {"TELEGRAM_BRIDGE_HOME": str(config), "TELECODE_SERVICE_APP_DIR": str(app)}), \
                 patch.object(service_manager, "_mac_plist_path", return_value=plist_path):
                generated = service_manager.generate_macos_plist()
            with generated.open("rb") as stream:
                plist = plistlib.load(stream)
            self.assertEqual(plist["Label"], "org.telecode.telegram-bridge")
            self.assertEqual(plist["ProgramArguments"][1:], [str(app / "telegram-bridge.py"), "listen"])
            self.assertEqual(plist["EnvironmentVariables"]["TELEGRAM_BRIDGE_HOME"], str(config.resolve()))
            if os.name != "nt":
                self.assertEqual(generated.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
