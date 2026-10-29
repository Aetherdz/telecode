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
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_BUTTONS.clear()
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
        self.assertTrue(labels["ses_aaaaaa111111"].startswith("alpha ["))
        self.assertTrue(labels["ses_bbbbbb222222"].startswith("beta ["))
        duplicate = [{"id": "ses_aaaaaa111111", "title": "alpha"},
                     {"id": "ses_bbbbbb222222", "title": "alpha"}]
        labels = tb._session_buttons(duplicate)
        self.assertNotEqual(labels["ses_aaaaaa111111"], labels["ses_bbbbbb222222"])

    def test_session_button_suffix_expands_on_collision(self):
        sessions = [{"id": "ses_aaaaaa111111", "title": "alpha"},
                    {"id": "ses_bbbbbb111111", "title": "alpha"}]
        labels = tb._session_buttons(sessions)
        self.assertNotEqual(labels["ses_aaaaaa111111"], labels["ses_bbbbbb111111"])
        self.assertTrue(all("[" in label for label in labels.values()))

    def test_session_title_is_single_line(self):
        self.assertEqual(tb.session_title({"title": "a\nb"}), "a b")
        self.assertEqual(tb.session_title({}), "Untitled")

    def test_stale_unique_session_label_is_never_forwarded_as_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        label = tb._session_buttons([{"id": "ses_abcdef123456", "title": "work"}])["ses_abcdef123456"]
        self.assertFalse(label == "work")
        with patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, label))
        send.assert_called_once()

    def test_html_escape_handles_markup_characters(self):
        self.assertEqual(tb._html_escape("A&B <x>"), "A&amp;B &lt;x&gt;")

    def test_formatted_message_retries_as_plain_text(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "api", side_effect=[ValueError("bad entities"), {"result": {"message_id": 1}}]) as api:
            self.assertEqual(tb.send_text(cfg, "<b>safe</b>", parse_mode="HTML"), 1)
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[2]["text"], "safe")
        self.assertNotIn("parse_mode", api.call_args.args[2])

    def test_inline_formatted_send_retries_as_plain_text(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "api", side_effect=[ValueError("bad HTML"), {"ok": True}]) as api:
            tb._send_inline(cfg, "<b>models</b>", [[{"text": "Close", "callback_data": "mdl:x"}]])
        self.assertEqual(api.call_count, 2)
        self.assertNotIn("parse_mode", api.call_args.args[2])
        self.assertEqual(api.call_args.args[2]["text"], "models")

    def test_reply_keyboard_picker_falls_back_to_plain_text(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "api", side_effect=[ValueError("bad HTML"), {"ok": True}]) as api:
            tb._send_reply_picker(cfg, "<b>models</b>", [[{"text": "Close"}]], "Pick")
        self.assertEqual(api.call_count, 2)
        self.assertEqual(api.call_args.args[2]["text"], "models")
        self.assertNotIn("parse_mode", api.call_args.args[2])
        markup = __import__("json").loads(api.call_args.args[2]["reply_markup"])
        self.assertFalse(markup["is_persistent"])
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("input_field_placeholder", markup)

    def test_session_picker_uses_one_bottom_keyboard_message_only(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        sessions = [{"id": "ses_abcdefgh", "title": "work"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "api") as api, patch.object(tb, "_send_keyboard") as top_keyboard:
            tb._send_session_picker(cfg)
        self.assertEqual(api.call_count, 1)
        self.assertEqual(api.call_args.args[1], "sendMessage")
        markup = __import__("json").loads(api.call_args.args[2]["reply_markup"])
        self.assertEqual(markup["keyboard"][0][0]["text"], "work [cdefgh]")
        top_keyboard.assert_not_called()

    def test_provider_and_model_picker_transition_posts_no_keyboard_reset_message(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        models = [{"id": "m1", "providerID": "provider", "name": "Model one"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "api") as api, \
             patch.object(tb, "_send_picker_notice"), \
             patch.object(tb, "_load_models_message_ref", return_value='{"chat_id":"17","message_id":"42"}'), \
             patch.object(tb, "_set_models_message_ref"):
            tb._models_menu(cfg)
            self.assertEqual(api.call_count, 2)
            self.assertTrue(tb.handle_control_message(cfg, {}, "provider (1)"))
        # First picker is sent; provider transition edits the same message.
        methods = [call.args[1] for call in api.call_args_list]
        self.assertEqual(methods[:2], ["editMessageText", "editMessageReplyMarkup"])
        self.assertEqual(methods.count("sendMessage"), 2)  # original picker + chosen provider page

    def test_model_picker_edits_existing_message_when_reply_markup_edit_supported(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        models = [{"id": "m1", "providerID": "provider", "name": "Model one"}]
        ref = '{"chat_id":"17","message_id":42}'
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_load_models_message_ref", return_value=ref), \
             patch.object(tb, "_set_models_message_ref") as save_ref, \
             patch.object(tb, "api", return_value={"ok": True}) as api, \
             patch.object(tb, "_send_reply_picker") as send_new:
            tb._models_menu(cfg)
        self.assertTrue(any(call.args[1] == "editMessageText" for call in api.call_args_list))
        send_new.assert_not_called()
        save_ref.assert_called_with({"chat_id": "17", "message_id": "42"})

    def test_model_picker_edit_uses_text_then_reply_markup_update(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with patch.object(tb, "api", return_value={"ok": True}) as api, \
             patch.object(tb, "_set_models_message_ref"):
            self.assertTrue(tb._edit_reply_picker(cfg, '{"chat_id":"17","message_id":42}',
                                                  "menu", [[{"text": "x"}]], "Pick"))
        self.assertEqual([call.args[1] for call in api.call_args_list],
                         ["editMessageText", "editMessageReplyMarkup"])

    def test_saved_picker_message_ref_must_be_unexpired_and_nonempty(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "models-cache.json"
            ref = cache.with_name("models-message.json")
            with patch.object(tb, "MODELS_CACHE", cache):
                ref.write_text('{"chat_id":"17","message_id":"42","expires":1}')
                self.assertEqual(tb._load_models_message_ref(), "")
                ref.write_text('{"chat_id":"","message_id":"","expires":9999999999}')
                self.assertEqual(tb._load_models_message_ref(), "")

    def test_model_picker_sends_bottom_reply_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        models = [{"id": "m1", "providerID": "test", "name": "Model 1"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_send_keyboard"), patch.object(tb, "api") as api:
            tb._models_menu(cfg)
        markup = __import__("json").loads(api.call_args.args[2]["reply_markup"])
        self.assertIn("keyboard", markup)
        self.assertNotIn("inline_keyboard", markup)
        self.assertFalse(markup["is_persistent"])
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("input_field_placeholder", markup)
        self.assertEqual(markup["keyboard"][0][0]["text"], "test (1)")

    def test_model_close_does_not_resend_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_send_keyboard") as show:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        show.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_model_close_removes_saved_model_message_reference(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_send_keyboard"), patch.object(tb, "_invalidate_model_message_ref") as save:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        save.assert_called_once()

    def test_startup_keyboard_has_model_selection_controls(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_configure_commands") as configure, patch.object(tb, "api") as api:
            tb._send_keyboard(cfg)
        import json
        markup = json.loads(api.call_args.args[2]["reply_markup"])
        self.assertFalse(markup["is_persistent"])
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("input_field_placeholder", markup)
        labels = [button["text"] for row in markup["keyboard"] for button in row]
        self.assertIn("Models", labels)
        self.assertIn("/models", labels)
        configure.assert_not_called()

    def test_session_picker_empty_results_do_not_reissue_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "list_sessions", return_value=[]), \
             patch.object(tb, "send_text") as message, \
             patch.object(tb, "_send_keyboard") as keyboard:
            tb._send_session_picker(cfg)
        message.assert_called_once()
        keyboard.assert_not_called()

    def test_files_command_exits_model_picker_without_resending_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", None)), \
             patch.object(tb, "send_text"), patch.object(tb, "_send_keyboard") as keyboard:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Files"))
        keyboard.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_startup_configures_commands_only_when_requested(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_configure_commands") as configure, patch.object(tb, "api"):
            tb._send_keyboard(cfg, configure=True)
        configure.assert_called_once_with(cfg)

    def test_sessions_picker_buttons_route_to_reply_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_send_session_picker") as picker:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Sessions"))
        picker.assert_called_once_with(cfg)

    def test_provider_and_model_buttons_route_to_bottom_reply_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "m1", "providerID": "p", "name": "Model one"}]
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "_hide_picker_keyboard"), \
             patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_read_models_cache", return_value=models):
            self.assertTrue(tb.handle_control_message(cfg, {}, "Models"))
            self.assertTrue(tb.handle_control_message(cfg, {}, "p (1)"))
        self.assertEqual(picker.call_count, 2)
        self.assertEqual(tb.ACTIVE_PICKER, "models")

    def test_open_picker_resets_state_from_previous_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [{"id": "ses_old0001", "title": "old"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_BUTTONS["old"] = "ses_old0001"
        models = [{"id": "m", "providerID": "p", "name": "Model"}]
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_send_reply_picker"), patch.object(tb, "_read_models_cache", return_value=models):
            self.assertTrue(tb.handle_control_message(cfg, {}, "/models"))
            self.assertFalse(tb.handle_control_message(cfg, {}, "old"))
        self.assertEqual(tb.ACTIVE_PICKER, "providers")
        self.assertEqual(tb.SESSION_BUTTONS, {})
        self.assertEqual(tb.SESSION_SNAPSHOT, [])

    def test_models_command_registers_usable_command_menu(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "api") as api:
            tb._configure_commands(cfg)
        self.assertEqual(api.call_args.args[1], "setMyCommands")
        commands = __import__("json").loads(api.call_args.args[2]["commands"])
        self.assertIn({"command": "models", "description": "Choose a model"}, commands)
        self.assertIn({"command": "model", "description": "Choose a model"}, commands)
        self.assertIn({"command": "files", "description": "List received files"}, commands)
        self.assertIn({"command": "start", "description": "Show TeleCode controls"}, commands)
        self.assertIn({"command": "current", "description": "Show the active session"}, commands)

    def test_close_models_button_does_not_close_session_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        with patch.object(tb, "_hide_picker_keyboard") as hide:
            handled = tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE)
        self.assertFalse(handled)
        hide.assert_not_called()

    def test_menu_command_resets_picker_state_without_resending_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [{"id": "ses_abcdef1", "title": "stale"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_BUTTONS["stale"] = "ses_abcdef1"
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_keyboard") as show:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/menu"))
        show.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)
        self.assertEqual(tb.SESSION_SNAPSHOT, [])
        self.assertEqual(tb.SESSION_BUTTONS, {})

    def test_current_command_shows_session_instead_of_becoming_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_session_by_id", return_value={"id": "ses_abcdefgh", "title": "work"}), \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/current"))
        self.assertIn("work", send.call_args.args[1])

    def test_help_controls_escape_model_picker_and_show_help(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Help"))
        self.assertIsNone(tb.ACTIVE_PICKER)
        send.assert_called_once()

    def test_sessions_button_escapes_model_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_session_picker") as picker:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Sessions"))
        picker.assert_called_once_with(cfg)

    def test_current_session_button_escapes_model_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        tb.MODEL_SELECTION.update(provider=0, page=0, labels={})
        with patch.object(tb, "_hide_picker_keyboard"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_session_by_id", return_value={"id": "ses_abcdefgh", "title": "work"}), \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Current session"))
        self.assertIn("work", send.call_args.args[1])
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_orphaned_pagination_control_is_consumed(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Next"))
        send.assert_not_called()

    def test_files_command_is_registered_and_consumed_from_model_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_hide_picker_keyboard"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "FILES", pathlib.Path("/tmp/nonexistent-telecode-test")), \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/files"))
        send.assert_called_once()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_start_resets_session_pagination(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.SESSION_PAGE = 2
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "send_text"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "/start"))
        self.assertEqual(tb.SESSION_PAGE, 0)

    def test_session_control_title_is_disambiguated(self):
        sessions = [{"id": "ses_control1", "title": "Cancel"},
                    {"id": "ses_control2", "title": "More models"}]
        labels = tb._session_buttons(sessions)
        self.assertNotEqual(labels["ses_control1"], "Cancel")
        self.assertNotEqual(labels["ses_control2"], tb.MODEL_NEXT)

    def test_model_button_from_old_page_cannot_select_current_page_model(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        old = [{"id": f"old-{n}", "providerID": "p", "name": f"Model {n}"} for n in range(9)]
        current = [{"id": "new-id", "providerID": "p", "name": "Different page item"}]
        with patch.object(tb, "_send_reply_picker"), patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_read_models_cache", return_value=old), patch.object(tb, "_send_keyboard"):
            tb._models_menu(cfg, provider_index=0, page=0, models_snapshot=old)
            tb._models_menu(cfg, provider_index=0, page=1, models_snapshot=old)
            with patch.object(tb, "_read_models_cache", return_value=current), \
                 patch.object(tb, "_switch_session_model") as switch:
                handled = tb.handle_control_message(cfg, {}, "Model 8")
        self.assertFalse(handled)
        switch.assert_not_called()

    def test_stale_model_label_does_not_switch_different_catalog_model(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        tb.MODEL_SELECTION.update(provider=0, page=0, labels={"Model": 0},
                                  models={"Model": ("p", "old-id")})
        changed_catalog = [{"id": "new-id", "providerID": "p", "name": "Model"}]
        with patch.object(tb, "_read_models_cache", return_value=changed_catalog), \
             patch.object(tb, "_switch_session_model") as switch, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Model"))
        switch.assert_not_called()
        send.assert_called_once()

    def test_session_label_cannot_select_outside_active_page(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{n:06d}", "title": f"session {n}"} for n in range(12)]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), patch.object(tb, "api"), \
             patch.object(tb, "send_text"), patch.object(tb, "_set_active_session") as select:
            tb._send_session_picker(cfg, page=0, sessions=sessions)
            handled = tb.handle_control_message(cfg, {}, "session 10")
        self.assertFalse(handled)
        select.assert_not_called()

    def test_models_command_disables_old_session_selection(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [{"id": "ses_abcdef123", "title": "old"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_BUTTONS["old"] = "ses_abcdef123"
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_models_from_api", return_value=[{"id": "m", "providerID": "p", "name": "M"}]), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "_send_reply_picker"), \
             patch.object(tb, "_set_active_session") as set_session:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/models"))
            handled = tb.handle_control_message(cfg, {}, "old")
        self.assertFalse(handled)
        set_session.assert_not_called()

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

    def test_models_picker_uses_html_parse_mode_and_plain_button_labels(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "gpt_5.1", "providerID": "openai", "name": "GPT <fast> & safe"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_current_model", return_value="gpt_5.1") as current_model, \
             patch.object(tb, "api") as api:
            tb._models_menu(cfg)
        payload = api.call_args.args[2]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("Choose a model provider", payload["text"])
        current_model.assert_not_called()
        keyboard = __import__("json").loads(payload["reply_markup"])["keyboard"]
        self.assertTrue(any(row[0]["text"].startswith("openai") for row in keyboard))
        self.assertTrue(all("callback_data" not in button for row in keyboard for button in row))

    def test_model_page_looks_up_current_model_only_after_provider_selection(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "gpt_5.1", "providerID": "openai", "name": "GPT 5.1"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_current_model", return_value="gpt_5.1") as current_model, \
             patch.object(tb, "api") as api:
            tb._models_menu(cfg, provider_index=0)
        current_model.assert_called_once_with(cfg, "ses_abcdefgh")
        self.assertIn("Current model", api.call_args.args[2]["text"])

    def test_models_use_reply_keyboard_pages_and_select_correct_model(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "id-1", "providerID": "provider", "name": "Repeated"},
                  {"id": "id-2", "providerID": "provider", "name": "Repeated"}]
        with patch.object(tb, "_send_reply_picker") as menu, \
             patch.object(tb, "_load_models_message_ref", return_value=""), \
             patch.object(tb, "_set_models_message_ref"), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_switch_session_model") as switch, \
             patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_read_models_cache", return_value=models):
            tb._models_menu(cfg, provider_index=0, models_snapshot=models)
            rows = menu.call_args.args[2]
            self.assertEqual(rows[0][0]["text"], "Repeated")
            self.assertEqual(rows[1][0]["text"], "Repeated [2]")
            self.assertEqual(rows[-1][0]["text"], tb.MODEL_BACK)
            self.assertTrue(tb.handle_control_message(cfg, {}, "Repeated [2]"))
        switch.assert_called_once_with(cfg, models[1])

    def test_back_from_model_picker_stays_in_control_keyboard_flow(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "id-1", "providerID": "provider", "name": "One"}]
        with patch.object(tb, "_send_reply_picker"), patch.object(tb, "_send_keyboard") as keyboard, \
             patch.object(tb, "_load_models_message_ref", return_value=""), \
             patch.object(tb, "_set_models_message_ref"), \
             patch.object(tb, "_read_models_cache", return_value=models):
            tb._models_menu(cfg, models_snapshot=models)
            tb._models_menu(cfg, provider_index=0, models_snapshot=models)
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_BACK))
        self.assertEqual(keyboard.call_count, 0)
        self.assertIsNone(tb.MODEL_SELECTION["provider"])

    def test_stale_model_back_from_provider_menu_is_ignored(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "providers"
        with patch.object(tb, "_hide_picker_keyboard") as hide:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_BACK))
        hide.assert_not_called()

    def test_session_picker_escapes_dynamic_values_for_html(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abc1234567", "title": "fix_auth.v2"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value="ses_abc1234567"), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg)
        payload = api.call_args.args[2]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("<b>fix_auth.v2 [234567]</b>", payload["text"])
        self.assertIn("<code>ses_abc1234567</code>", payload["text"])

    def test_session_picker_formatted_send_falls_back_to_plain_text(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abc1234567", "title": "A < B"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "api", side_effect=[ValueError("parse error"), {"ok": True}]) as api:
            tb._send_session_picker(cfg)
        self.assertEqual(api.call_count, 2)
        self.assertNotIn("parse_mode", api.call_args.args[2])
        self.assertIn("A < B", api.call_args.args[2]["text"])

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

    def test_session_listing_retries_unfiltered_when_filtered_result_is_empty(self):
        cfg = {"TG_BOT_TOKEN": "unused"}
        fallback = [{"id": "ses_aaaaaa", "directory": str(pathlib.Path.home()), "time": {}}]
        with patch.object(tb, "_session_items", side_effect=[[], fallback]) as listing:
            result = tb.list_sessions(cfg)
        self.assertEqual([item["id"] for item in result], ["ses_aaaaaa"])
        self.assertEqual(listing.call_count, 2)

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
        labels = [row[0]["text"] for row in keyboard if row and row[0]["text"] not in ("Previous", "Next", "Cancel", "/menu")]
        self.assertEqual(len(labels), 8)
        body = payload["text"]
        self.assertIn("9. <b>session 8 [000008]</b>", body)
        self.assertNotIn("1. <b>session 0</b>", body)
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_session_page_change_reuses_one_session_snapshot(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(20)]
        tb.SESSION_SNAPSHOT = []
        tb.SESSION_BUTTONS.clear()
        with patch.object(tb, "list_sessions", return_value=sessions) as listing, \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "api"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "Next"))
        listing.assert_called_once()
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_keyboard_button_ignores_unicode_variation_selector(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_send_session_picker") as picker:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Sessions\ufe0f"))
        picker.assert_called_once()

    def test_keyboard_labels_are_english(self):
        buttons = [button["text"] for row in tb._keyboard({})["keyboard"] for button in row]
        self.assertEqual(buttons, ["Sessions", "Current session", "Models", "Help",
                                   "/menu", "/session", "/models"])

    def test_model_provider_keyboard_renders_page_with_same_reply_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        snapshot = [{"id": "m1", "providerID": "p", "name": "Model"}]
        with patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_models_from_api", side_effect=AssertionError("must not reload")), \
             patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_load_models_message_ref", return_value=""):
            tb._models_menu(cfg, provider_index=0, page=0, models_snapshot=snapshot)
        self.assertEqual(picker.call_args.args[2][0][0]["text"], "Model")
        self.assertEqual(picker.call_args.args[2][-1][0]["text"], tb.MODEL_BACK)

    def test_model_page_navigation_updates_page_then_back_returns_to_providers(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": f"id-{n}", "providerID": "p", "name": f"Model {n}"} for n in range(10)]
        with patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_load_models_message_ref", return_value=""), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_read_models_cache", return_value=models):
            tb._models_menu(cfg, provider_index=0, models_snapshot=models)
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_NEXT))
            self.assertEqual(tb.MODEL_SELECTION["page"], 1)
            self.assertEqual(picker.call_args.args[2][0][0]["text"], "Model 8")
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_BACK))
            self.assertIsNone(tb.MODEL_SELECTION["provider"])
        self.assertEqual(picker.call_args.args[2][0][0]["text"], "p (10)")

    def test_model_provider_selection_uses_bottom_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "model-id", "providerID": "provider", "name": "Model"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "_send_keyboard"), \
             patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_read_models_cache", return_value=models):
            tb._models_menu(cfg)
            self.assertTrue(tb.handle_control_message(cfg, {}, "provider (1)"))
        self.assertEqual(picker.call_count, 2)

    def test_session_picker_tracks_button_id_and_prevents_title_alias_selection(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abcdef111", "title": "same"},
                    {"id": "ses_abcdef222", "title": "same"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_SNAPSHOT = []
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), patch.object(tb, "api"), \
             patch.object(tb, "_set_active_session") as select, patch.object(tb, "send_text"):
            tb._send_session_picker(cfg, sessions=sessions)
            label = next(label for label in tb.SESSION_BUTTONS if label.startswith("same"))
            self.assertTrue(tb.handle_control_message(cfg, {}, label))
        select.assert_called_once_with(sessions[0])

    def test_module_has_no_emoji_in_ui_strings(self):
        source = BRIDGE.read_text(encoding="utf-8")
        emoji = [ch for ch in source if ord(ch) >= 0x1F000]
        self.assertEqual(emoji, [])


if __name__ == "__main__":
    unittest.main()
