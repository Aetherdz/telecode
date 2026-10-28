import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch
import sys


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "tg_bridge.py"
sys.path.insert(0, str(BRIDGE.parent))
spec = importlib.util.spec_from_file_location("telegram_bridge", BRIDGE)
tb = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tb
spec.loader.exec_module(tb)


class SessionRoutingTests(unittest.TestCase):
    def test_session_label_contains_full_id(self):
        sid = "ses_abcdefghijk12345"
        self.assertTrue(tb.session_label({"id": sid, "title": "chat"}).endswith(f"[{sid}]"))

    def test_active_session_is_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                tb._set_active_session({"id": "ses_abcdefgh", "title": "test", "directory": temp})
                self.assertEqual(tb._active_session_id(), "ses_abcdefgh")
                self.assertEqual(active.stat().st_mode & 0o777, 0o600)

    def test_sendfile_path_allowlist_blocks_outside_paths(self):
        from tg_mcp import _h_sendfile

        with tempfile.TemporaryDirectory() as temp, tempfile.NamedTemporaryFile() as f:
            with patch.dict("os.environ", {"TG_SEND_ROOTS": temp}):
                with self.assertRaises(ValueError):
                    _h_sendfile({"path": f.name})

    def test_claude_code_adapter_fails_closed(self):
        from adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with self.assertRaises(NotImplementedError):
            adapter.send_message("session-id", "hello")

    def test_stale_session_button_does_not_become_agent_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "list_sessions", return_value=[]), \
             patch.object(tb, "send_text") as send:
            handled = tb.handle_control_message(cfg, {}, "Old Session [ses_abcdefgh]")
        self.assertTrue(handled)
        send.assert_called_once()

    def test_session_buttons_are_name_first_and_unique(self):
        sessions = [
            {"id": "ses_aaaaaa111111", "title": "alpha"},
            {"id": "ses_bbbbbb222222", "title": "beta"},
        ]
        labels = tb._session_buttons(sessions)
        self.assertEqual(labels["ses_aaaaaa111111"], "alpha")
        self.assertEqual(labels["ses_bbbbbb222222"], "beta")
        duplicate = [{"id": "ses_aaaaaa111111", "title": "alpha"},
                     {"id": "ses_bbbbbb222222", "title": "alpha"}]
        labels = tb._session_buttons(duplicate)
        self.assertNotEqual(labels["ses_aaaaaa111111"], labels["ses_bbbbbb222222"])

    def test_session_title_is_single_line(self):
        self.assertEqual(tb.session_title({"title": "a\nb"}), "a b")
        self.assertEqual(tb.session_title({}), "Untitled")

    def test_markdown_v2_escape_handles_reserved_characters(self):
        self.assertEqual(tb._mdv2_escape("a_b.c"), r"a\_b\.c")

    def test_inject_success_does_not_send_acknowledgement(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1", "TG_DELIVERY": "steer"}
        rec = {"update_id": 10, "text": "hello", "session_id": ""}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(tb, "STATE", pathlib.Path(temp) / "wake-session.txt"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_try_prompt", return_value=True), \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.inject_record(cfg, rec))
        send.assert_not_called()

    def test_models_cache_roundtrip_is_private(self):
        models = [
            {"id": "openai/gpt", "providerID": "openrouter", "name": "GPT"},
            {"id": "gemini", "providerID": "google", "name": "Gemini"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "models-cache.json"
            with patch.object(tb, "MODELS_CACHE", cache):
                tb._write_models_cache(models)
                self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
                self.assertEqual(tb._read_models_cache(), models)

    def test_models_cache_rejects_corrupt_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "models-cache.json"
            cache.write_text("{not json")
            with patch.object(tb, "MODELS_CACHE", cache):
                self.assertEqual(tb._read_models_cache(), [])

    def test_group_models_is_sorted_and_grouped(self):
        models = [
            {"id": "b", "providerID": "p", "name": "Beta"},
            {"id": "a", "providerID": "p", "name": "Alpha"},
            {"id": "c", "providerID": "q", "name": "Gamma"},
        ]
        groups = tb._group_models(models)
        self.assertEqual([m["id"] for m in groups["p"]], ["a", "b"])
        self.assertEqual(tb._ordered_providers(groups)[0], "p")

    def test_unknown_callback_data_is_ignored(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "send_text") as send, \
             patch.object(tb, "_models_menu") as menu:
            handled = tb.handle_callback(cfg, {"data": "something-else"})
        self.assertFalse(handled)
        send.assert_not_called()
        menu.assert_not_called()

    def test_models_picker_uses_english_markdown_v2(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "gpt_5.1", "providerID": "openai", "name": "GPT_5.1"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_current_model", return_value="gpt_5.1"), \
             patch.object(tb, "api") as api:
            tb._models_menu(cfg)
        payload = api.call_args.args[2]
        self.assertEqual(payload["parse_mode"], "MarkdownV2")
        self.assertIn("Choose a model provider", payload["text"])
        self.assertTrue(any(label.startswith("openai") for label in
                            [row[0]["text"] for row in __import__("json").loads(payload["reply_markup"])["inline_keyboard"]]))

    def test_session_picker_escapes_dynamic_values_for_markdown_v2(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abc1234567", "title": "fix_auth.v2"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value="ses_abc1234567"), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg)
        payload = api.call_args.args[2]
        self.assertEqual(payload["parse_mode"], "MarkdownV2")
        self.assertIn(r"fix\_auth\.v2", payload["text"])
        self.assertIn(r"ses\_abc1234567", payload["text"])

    def test_session_listing_falls_back_when_directory_filter_is_unsupported(self):
        cfg = {"TG_BOT_TOKEN": "unused"}
        all_sessions = [
            {"id": "ses_aaaaaa", "directory": str(pathlib.Path.home()), "time": {}},
            {"id": "ses_bbbbbb", "directory": "/tmp/other", "time": {}},
            {"id": "ses_cccccc", "parentID": "ses_parent", "directory": str(pathlib.Path.home()), "time": {}},
            {"id": "ses_dddddd", "directory": str(pathlib.Path.home()), "time": {"archived": 1}},
        ]
        with patch.object(tb, "_session_items", side_effect=[RuntimeError("filter unsupported"), all_sessions]):
            result = tb.list_sessions(cfg)
        self.assertEqual([item["id"] for item in result], ["ses_aaaaaa"])

    def test_session_picker_displays_only_the_selected_page(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(20)]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg, page=1)
        payload = api.call_args.args[2]
        keyboard = __import__("json").loads(payload["reply_markup"])["keyboard"]
        labels = [row[0]["text"] for row in keyboard if row and row[0]["text"] not in ("Previous", "Next", "Cancel")]
        self.assertEqual(len(labels), 8)
        body = payload["text"]
        self.assertIn("9\\.", body)
        self.assertNotIn("1\\. *session 0*", body)
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_session_page_change_reuses_one_session_snapshot(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(20)]
        with patch.object(tb, "list_sessions", return_value=sessions) as listing, \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "api"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "Next"))
        listing.assert_called_once()
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_module_has_no_emoji_in_ui_strings(self):
        source = BRIDGE.read_text(encoding="utf-8")
        emoji = [ch for ch in source if ord(ch) >= 0x1F000]
        self.assertEqual(emoji, [])


if __name__ == "__main__":
    unittest.main()
