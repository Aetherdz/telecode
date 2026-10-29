import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "setup_cli.py"
spec = importlib.util.spec_from_file_location("setup_cli", SCRIPT)
setup_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_cli)


class CliSetupTests(unittest.TestCase):
    def test_cli_setup_cancellation_returns_failure_to_installer(self):
        with patch.object(setup_cli, "selectable_hosts", return_value=[setup_cli.HOSTS[-1]]), \
             patch.object(setup_cli, "choose", return_value=None):
            self.assertEqual(setup_cli.main(), 2)

    def test_manual_client_setup_is_successful_nonautomatic_path(self):
        with patch.object(setup_cli, "selectable_hosts", return_value=[setup_cli.HOSTS[-1]]), \
             patch.object(setup_cli, "choose", return_value=setup_cli.HOSTS[-1]):
            self.assertEqual(setup_cli.main(), 0)

    def test_detected_cli_options_do_not_include_undetected_integrations(self):
        with patch.object(setup_cli, "discover", side_effect=lambda host: (host[1] == "claude", None, host[3])):
            labels = [host[0] for host in setup_cli.selectable_hosts()]
        self.assertEqual(labels, ["Claude Code", "Other MCP client"])

    def test_wordmark_alignment(self):
        self.assertEqual(setup_cli.APPROVED_WORDMARK_WIDTH, 47)

    def test_codex_toml_preserves_existing_settings(self):
        original = '[model]\nmodel = "test"\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.toml"
            path.write_text(original)
            result = setup_cli.register_codex_toml(path)
        self.assertIn(original.strip(), result)
        self.assertIn("[mcp_servers.telegram-bridge]", result)

    def test_codex_toml_refuses_duplicate_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.toml"
            path.write_text('[mcp_servers.telegram-bridge]\ncommand="python"\n')
            with self.assertRaises(ValueError):
                setup_cli.register_codex_toml(path)

    def test_invalid_json_schema_refused(self):
        host = ("OpenCode", "opencode", [], True)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text('{"mcp": []}')
            with self.assertRaises(ValueError):
                setup_cli.register_json(path, host)

    def test_existing_json_server_refused(self):
        host = ("OpenCode", "opencode", [], True)
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text('{"mcp":{"servers":{"telegram-bridge":{}}}}')
            with self.assertRaises(ValueError):
                setup_cli.register_json(path, host)

    def test_atomic_write_preserves_private_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text("{}")
            path.chmod(0o600)
            setup_cli.atomic_write(path, '{"ok": true}\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), '{"ok": true}\n')


if __name__ == "__main__":
    unittest.main()
