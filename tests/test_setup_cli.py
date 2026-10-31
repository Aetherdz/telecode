import importlib.util
import os
import pathlib
import tempfile
import unittest
import builtins
from unittest.mock import patch

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "setup_cli.py"
spec = importlib.util.spec_from_file_location("setup_cli", SCRIPT)
setup_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_cli)


class CliSetupTests(unittest.TestCase):
    def test_menu_display_width_handles_ansi_and_wide_characters(self):
        text = "\033[31m界e\u0301\033[0m"
        self.assertEqual(setup_cli._columns(text), 3)
        self.assertEqual(setup_cli._columns(setup_cli._pad_display(text, 5)), 5)

    def test_empty_setup_option_list_fails_cleanly(self):
        with patch.object(setup_cli, "selectable_hosts", return_value=[]):
            self.assertEqual(setup_cli.main(), 2)

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

    @unittest.skipIf(os.name == "nt", "termios raw-mode selector is unavailable on Windows")
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
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.read_text(), '{"ok": true}\n')

    @unittest.skipUnless(os.name == "posix", "POSIX mode bits are not portable")
    def test_atomic_write_new_file_mode_is_exactly_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "new-config.json"
            setup_cli.atomic_write(path, "private\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_atomic_write_chmod_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text("original\n")
            temp_files_before = set(path.parent.iterdir())
            if not hasattr(os, "fchmod"):
                self.skipTest("fchmod failure injection is unavailable on this platform")
            with patch("setup_cli.os.fchmod", side_effect=OSError("chmod failed")):
                with self.assertRaisesRegex(OSError, "chmod failed"):
                    setup_cli.atomic_write(path, "replacement\n")
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), temp_files_before)

    def test_atomic_write_replace_failure_preserves_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text("original\n")
            before = set(path.parent.iterdir())
            with patch.object(setup_cli.os, "replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    setup_cli.atomic_write(path, "replacement\n")
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), before)

    def test_atomic_write_replace_failure_does_not_close_descriptor_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            real_fdopen = setup_cli.os.fdopen
            opened = []
            class TrackingStream:
                def __init__(self, stream): self.stream = stream
                def __enter__(self): return self
                def __exit__(self, *args): return self.stream.__exit__(*args)
                def write(self, *args): return self.stream.write(*args)
                def flush(self): return self.stream.flush()
                def fileno(self): return self.stream.fileno()
                @property
                def closed(self): return self.stream.closed
            def tracking_fdopen(fd, *args, **kwargs):
                stream = TrackingStream(real_fdopen(fd, *args, **kwargs))
                opened.append(stream)
                return stream
            with patch.object(setup_cli.os, "fdopen", side_effect=tracking_fdopen), \
                 patch.object(setup_cli.os, "replace", side_effect=OSError("replace failed")), \
                 patch.object(setup_cli.os, "close", wraps=setup_cli.os.close) as close:
                with self.assertRaisesRegex(OSError, "replace failed"):
                    setup_cli.atomic_write(path, "replacement\n")
            self.assertEqual(len(opened), 1)
            self.assertTrue(opened[0].closed)
            close.assert_not_called()
            self.assertFalse(list(path.parent.glob(".config.json.*.tmp")))

    def test_atomic_write_interrupt_closes_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text("original\n")
            before = set(path.parent.iterdir())
            with patch("setup_cli.os.fsync", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    setup_cli.atomic_write(path, "replacement\n")
            self.assertEqual(path.read_text(), "original\n")
            self.assertEqual(set(path.parent.iterdir()), before)

    def test_atomic_write_directory_sync_unsupported_still_reports_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            real_open = setup_cli.os.open
            def fail_directory_open(candidate, flags, *args, **kwargs):
                if pathlib.Path(candidate) == path.parent:
                    raise PermissionError("directory handles unsupported")
                return real_open(candidate, flags, *args, **kwargs)
            with patch.object(setup_cli.os, "open", side_effect=fail_directory_open):
                setup_cli.atomic_write(path, "written\n")
            self.assertEqual(path.read_text(), "written\n")

    def test_non_tty_selector_uses_numbered_prompt(self):
        options = [setup_cli.HOSTS[0], setup_cli.HOSTS[-1]]
        with patch.object(setup_cli.sys.stdin, "isatty", return_value=False), \
             patch.object(setup_cli, "_choose_arrow") as arrow, \
             patch("builtins.input", return_value="2"):
            selected = setup_cli.choose(options)
        arrow.assert_not_called()
        self.assertIs(selected, options[1])

    def test_tty_arrow_selector_failure_falls_back_to_numbered_prompt(self):
        options = [setup_cli.HOSTS[0], setup_cli.HOSTS[-1]]
        class Tty:
            def isatty(self): return True
        with patch.object(setup_cli.sys, "stdin", Tty()), \
             patch.object(setup_cli.sys, "stdout", Tty()), \
             patch.object(setup_cli, "_choose_arrow", side_effect=ImportError("termios unavailable")), \
             patch.object(builtins, "input", return_value="2"), \
             patch("builtins.print"):
            selected = setup_cli.choose(options)
        self.assertIs(selected, options[1])

    def test_menu_rows_share_one_width(self):
        with patch.object(setup_cli, "discover", return_value=(True, None, True)), \
             patch.dict(setup_cli.os.environ, {"NO_COLOR": "1"}):
            lines = setup_cli._menu_lines([setup_cli.HOSTS[0], setup_cli.HOSTS[-1]], 0)
        box = lines[:4]  # top border, two rows, bottom border
        self.assertEqual(len({len(line) for line in box}), 1)
        self.assertIn("\u276f 1. OpenCode", lines[1])
        self.assertIn("manual setup", lines[2])

    def test_host_state_labels_detection_and_manual_setup(self):
        with patch.object(setup_cli, "discover",
                          side_effect=lambda host: (host[1] == "opencode",
                                                    host[1] in ("opencode", "cursor"),
                                                    host[3])):
            self.assertEqual(setup_cli.host_state(setup_cli.HOSTS[0]),
                             ("CLI + config found", "ok"))
            self.assertEqual(setup_cli.host_state(setup_cli.HOSTS[3]),
                             ("config found", "warn"))
        self.assertEqual(setup_cli.host_state(setup_cli.HOSTS[-1]),
                         ("manual setup", "dim"))

    def test_eof_during_confirmation_cancels_cleanly(self):
        host = setup_cli.HOSTS[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "opencode.json"
            with patch.object(setup_cli, "selectable_hosts", return_value=[host]), \
                 patch.object(setup_cli, "choose", return_value=host), \
                 patch.object(setup_cli, "discover", return_value=(True, path, True)), \
                 patch("builtins.input", side_effect=EOFError):
                self.assertEqual(setup_cli.main(), 2)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
