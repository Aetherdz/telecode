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

    def test_selector_highlights_current_choice_when_color_is_available(self):
        options = [setup_cli.HOSTS[0], setup_cli.HOSTS[-1]]
        with patch.object(setup_cli.sys.stdin, "isatty", return_value=False), \
             patch.object(setup_cli.sys.stdout, "isatty", return_value=True), \
             patch.object(setup_cli, "discover", return_value=(True, None, True)), \
             patch("builtins.input", return_value="q"), \
             patch("builtins.print") as output, \
             patch.dict(setup_cli.os.environ, {}, clear=True):
            setup_cli.choose(options)
        self.assertTrue(any("\033[1;38;2;48;179;239m" in call.args[0]
                            for call in output.call_args_list if call.args))

    def test_arrow_selector_moves_and_enter_confirms(self):
        class Input:
            def isatty(self): return True
            def fileno(self): return 0
            def __init__(self, value):
                self.keys = iter(["\x1b", "[B", "\r"])
                self.position = 0
            def read(self, n=-1):
                return next(self.keys, "")
        class Output:
            def isatty(self): return True
            def write(self, _text): return None
            def flush(self): return None
        options = [setup_cli.HOSTS[0], setup_cli.HOSTS[-1]]
        stream = Input("\x1b[B\r")
        with patch.object(setup_cli.sys, "stdin", stream), \
             patch.object(setup_cli.sys, "stdout", Output()), \
             patch.object(setup_cli, "discover", return_value=(True, None, True)), \
             patch("termios.tcgetattr", return_value=[]), patch("termios.tcsetattr"), \
             patch("tty.setraw"):
            selected = setup_cli.choose(options)
        self.assertIs(selected, options[1])

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
