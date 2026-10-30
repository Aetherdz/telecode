import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys


BRIDGE = pathlib.Path(__file__).resolve().parents[1] / "tg_bridge.py"
sys.path.insert(0, str(BRIDGE.parent))
spec = importlib.util.spec_from_file_location("tg_bridge", BRIDGE)
tb = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = tb
spec.loader.exec_module(tb)


class SessionRoutingTests(unittest.TestCase):
    def test_shim_forwards_main_entrypoint_patches(self):
        import telegram_bridge

        self.assertIs(tb.main, telegram_bridge.main)
        with patch.object(tb, "main") as mocked_main:
            self.assertIs(tb.main, mocked_main)
        self.assertIs(tb.main, telegram_bridge.main)

    def test_session_label_contains_full_id(self):
        sid = "ses_abcdefghijk12345"
        self.assertTrue(tb.session_label({"id": sid, "title": "chat"}).endswith(f"[{sid}]"))

    def test_active_session_is_atomic_and_private(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                tb._set_active_session({"id": "ses_abcdefgh", "title": "test", "directory": temp})
                self.assertEqual(tb._active_session_id(), "ses_abcdefgh")
                if os.name != "nt":
                    self.assertEqual(active.stat().st_mode & 0o777, 0o600)

    def test_active_session_record_stores_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                tb._set_active_session({"id": "ses_abcdefgh", "title": "test",
                                        "directory": temp, "agent": "codex"})
                self.assertEqual(tb._active_session_record().get("agent"), "codex")

    def test_active_session_rejected_when_agent_mismatches(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                tb._set_active_session({"id": "ses_abcdefgh", "title": "test",
                                        "directory": temp, "agent": "codex"})
                with patch.object(tb, "_agent_name", return_value="opencode"), \
                     patch.object(tb, "_session_by_id") as lookup:
                    self.assertFalse(tb._active_session_matches_agent({}))
                    lookup.assert_not_called()
                self.assertFalse(tb.resolve_session({"TELECODE_AGENT": "opencode"})[1] == "telegram-selected")

    def test_active_session_without_agent_field_stays_compatible(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                active.write_text('{"id": "ses_abcdefgh", "title": "old", "directory": "."}')
                self.assertTrue(tb._active_session_matches_agent({"TELECODE_AGENT": "codex"}))

    def test_resolve_session_clears_active_session_from_other_agent(self):
        with tempfile.TemporaryDirectory() as temp:
            active = pathlib.Path(temp) / "active-session.json"
            with patch.object(tb, "ACTIVE_SESSION", active):
                tb._set_active_session({"id": "ses_abcdefgh", "title": "test",
                                        "directory": temp, "agent": "codex"})
                with patch.object(tb, "_agent_name", return_value="opencode"), \
                     patch.object(tb, "_session_by_id", return_value={"id": "ses_abcdefgh"}) as lookup, \
                     patch.object(tb, "discover_session", return_value=None):
                    self.assertEqual(tb.resolve_session({}), ("", "none"))
                    lookup.assert_not_called()
                self.assertFalse(active.exists())

    def test_sendfile_path_allowlist_blocks_outside_paths(self):
        from tg_mcp import _h_sendfile

        with tempfile.TemporaryDirectory() as temp, tempfile.NamedTemporaryFile() as f:
            with patch.dict("os.environ", {"TG_SEND_ROOTS": temp}):
                with self.assertRaises(ValueError):
                    _h_sendfile({"path": f.name})

    def test_claude_code_adapter_resumes_session(self):
        from adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with patch.object(adapter, "binary", "true-claude"):
            with patch.object(tb.subprocess, "run") as run:
                run.return_value = tb.subprocess.CompletedProcess([], 0, stdout="done", stderr="")
                reply = adapter.send_message("0123abcd-00aa-22bb-33cc-44dd55ee66ff", "hello")
        self.assertEqual(reply, "done")
        self.assertIn("--resume", run.call_args.args[0])

    def test_claude_code_adapter_rejects_bad_session_id(self):
        from adapters.claude_code import ClaudeCodeAdapter
        adapter = ClaudeCodeAdapter()
        with patch.object(tb.subprocess, "run") as run:
            self.assertIsNone(adapter.send_message("not valid", "hello"))
        run.assert_not_called()

    def test_agent_adapter_respects_explicit_setting(self):
        from adapters.claude_code import ClaudeCodeAdapter
        from adapters.opencode import OpenCodeAdapter
        self.assertIsInstance(tb._agent_adapter({"TELECODE_AGENT": "claude-code"}), ClaudeCodeAdapter)
        self.assertIsInstance(tb._agent_adapter({"TELECODE_AGENT": "opencode"}), OpenCodeAdapter)

    def test_try_prompt_routes_through_selected_adapter(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TELECODE_AGENT": "opencode"}
        sent = {}
        class FakeAdapter:
            name = "fake"
            def send_message(self, sid, text, delivery="queue"):
                sent.update(sid=sid, text=text, delivery=delivery)
                return "ok"
        with patch.object(tb, "_agent_adapter", return_value=FakeAdapter()):
            self.assertTrue(tb._try_prompt(cfg, "ses_abcdefgh", "hello", "steer"))
        self.assertEqual(sent, {"sid": "ses_abcdefgh", "text": "hello", "delivery": "steer"})

    def test_try_prompt_rejects_invalid_session_id(self):
        with patch.object(tb, "_agent_adapter") as factory:
            self.assertFalse(tb._try_prompt({}, "not valid", "hello", "queue"))
        factory.assert_not_called()

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
        self.assertEqual(labels["ses_aaaaaa111111"], "1. alpha")
        self.assertEqual(labels["ses_bbbbbb222222"], "2. beta")
        duplicate = [{"id": "ses_aaaaaa111111", "title": "alpha"},
                     {"id": "ses_bbbbbb222222", "title": "alpha"}]
        labels = tb._session_buttons(duplicate)
        self.assertNotEqual(labels["ses_aaaaaa111111"], labels["ses_bbbbbb222222"])

    def test_session_button_numbers_disambiguate_duplicate_names(self):
        sessions = [{"id": "ses_aaaaaa111111", "title": "alpha"},
                    {"id": "ses_bbbbbb111111", "title": "alpha"}]
        labels = tb._session_buttons(sessions)
        self.assertNotEqual(labels["ses_aaaaaa111111"], labels["ses_bbbbbb111111"])
        self.assertEqual(set(labels.values()), {"1. alpha", "2. alpha"})

    def test_session_title_is_single_line(self):
        self.assertEqual(tb.session_title({"title": "a\nb"}), "a b")
        self.assertEqual(tb.session_title({}), "Untitled")

    def test_stale_unique_session_label_is_never_forwarded_as_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        tb.ACTIVE_PICKER = "sessions"
        label = tb._session_buttons([{"id": "ses_abcdef123456", "title": "work"}])["ses_abcdef123456"]
        self.assertEqual(label, "1. work")
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "send_text") as send, patch.object(tb, "_send_keyboard"):
            self.assertTrue(tb.handle_control_message(cfg, {}, label))
        send.assert_called_once()

    def test_non_session_bracket_suffix_is_not_mistaken_for_stale_session_button(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "send_text") as send:
            self.assertFalse(tb.handle_control_message(cfg, {}, "review the patch [feature123]"))
        send.assert_not_called()

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
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("is_persistent", markup)
        self.assertNotIn("input_field_placeholder", markup)

    def test_reply_keyboard_buttons_include_supported_color_styles(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        main = tb._keyboard(cfg)["keyboard"]
        by_text = {button["text"]: button for row in main for button in row}
        self.assertEqual(by_text["Sessions"]["style"], "primary")
        self.assertEqual(by_text["New session"]["style"], "success")
        self.assertEqual(by_text["Current session"]["style"], "success")
        self.assertEqual(by_text["Help"]["style"], "danger")
        self.assertEqual(tb._keyboard(cfg)["keyboard"], [
            [{"text": "Current session", "style": "success"},
             {"text": "New session", "style": "success"}],
            [{"text": "Models", "style": "primary"},
             {"text": "Sessions", "style": "primary"}],
            [{"text": "Help", "style": "danger"}],
        ])

        rows = [[{"text": "Next"}, {"text": "Cancel"}, {"text": "build-server"}]]
        with patch.object(tb, "api", return_value={"ok": True}) as api:
            tb._send_reply_picker(cfg, "Choose", rows, notify=False)
        markup = __import__("json").loads(api.call_args.args[2]["reply_markup"])
        buttons = {button["text"]: button for row in markup["keyboard"] for button in row}
        self.assertEqual(buttons["Next"]["style"], "primary")
        self.assertEqual(buttons["Cancel"]["style"], "danger")
        self.assertNotIn("style", buttons["build-server"])
        self.assertNotIn("style", rows[0][0])  # Styling must not mutate caller-owned rows.

    def test_inline_keyboard_buttons_include_supported_color_styles(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "api", return_value={"ok": True}) as api:
            tb._send_inline(cfg, "Choose", [[{"text": "Back", "callback_data": "back"}]])
        markup = __import__("json").loads(api.call_args.args[2]["reply_markup"])
        self.assertEqual(markup["inline_keyboard"][0][0]["style"], "primary")

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
        self.assertEqual(markup["keyboard"][0][0]["text"], "1. work")
        new_session_row = next(row for row in markup["keyboard"]
                               if any(button.get("text") == tb.NEW_SESSION for button in row))
        self.assertEqual(new_session_row[0]["style"], "success")
        self.assertEqual(new_session_row[1], {"text": "Open by ID", "style": "primary"})
        top_keyboard.assert_not_called()

    def test_empty_session_list_still_offers_create_session_action(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with patch.object(tb, "list_sessions", return_value=[]), \
             patch.object(tb, "_send_reply_picker") as picker:
            tb._send_session_picker(cfg)
        self.assertEqual(picker.call_args.args[2],
                         [[{"text": tb.NEW_SESSION}, {"text": "Open by ID"}], [{"text": "Cancel"}]])
        self.assertEqual(tb.ACTIVE_PICKER, "sessions")
        self.assertEqual(tb.SESSION_BUTTONS, {})
        with patch.object(tb, "_send_reply_picker"):
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_empty_session_picker_cancel_closes_without_extra_message(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = []
        with patch.object(tb, "_send_keyboard") as keyboard, patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Cancel"))
        keyboard.assert_called_once_with(cfg)
        send.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_session_picker_attachment_is_consumed_without_prompting_name(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "sessions"
        with patch.object(tb, "create_session") as create, patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {"document": {"file_id": "x"}}, "an upload"))
        create.assert_not_called()
        send.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "sessions")

    def test_new_session_action_in_session_picker_is_not_treated_as_name(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "sessions"
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        create.assert_not_called()
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_create_session_posts_title_and_configured_home_directory(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        created = {"id": "ses_created1", "title": "A new session"}
        with tempfile.TemporaryDirectory() as temp, \
             patch("pathlib.Path.home", return_value=pathlib.Path(temp)), \
             patch.object(tb, "_opencode_api", return_value={"data": created}) as call:
            session = tb.create_session(cfg, "  A   new session  ")
        self.assertEqual(session["title"], "A new session")
        self.assertEqual(session["id"], "ses_created1")
        self.assertEqual(call.call_args.args[1:3], ("post", "/api/session"))
        self.assertEqual(call.call_args.args[3], {"title": "A new session", "directory": str(pathlib.Path(temp).resolve())})

    def test_session_picker_attaches_create_action_to_every_page(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(25)]
        with patch.object(tb, "_active_session_id", return_value=""), patch.object(tb, "api"):
            for page in (0, 1):
                with self.subTest(page=page), patch.object(tb, "_send_reply_picker") as picker:
                    tb._send_session_picker(cfg, page=page, sessions=sessions)
                self.assertIn([{"text": tb.NEW_SESSION}, {"text": "Open by ID"}], picker.call_args.args[2])

    def test_new_session_button_and_slash_command_aliases_always_start_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        for picker_state in (None, "sessions", "models", "providers"):
            for command in (tb.NEW_SESSION,):
                tb.ACTIVE_PICKER = picker_state
                with self.subTest(state=picker_state, command=command), \
                     patch.object(tb, "_send_reply_picker") as prompt, \
                     patch.object(tb, "_invalidate_model_message_ref"), \
                     patch.object(tb, "create_session") as create, patch.object(tb, "send_text"):
                    self.assertTrue(tb.handle_control_message(cfg, {}, command))
                create.assert_not_called()
                prompt.assert_called_once()
                self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_create_session_rejects_api_directory_outside_configured_home(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        created = {"id": "ses_created1", "title": "A new session", "directory": "/tmp/elsewhere"}
        with tempfile.TemporaryDirectory() as temp, \
             patch("pathlib.Path.home", return_value=pathlib.Path(temp)), \
             patch.object(tb, "_opencode_api", return_value={"data": created}):
            with self.assertRaisesRegex(RuntimeError, "outside the configured home"):
                tb.create_session(cfg, "A new session")

    def test_create_session_accepts_api_directory_matching_configured_home(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with tempfile.TemporaryDirectory() as temp:
            home = pathlib.Path(temp).resolve()
            created = {"id": "ses_created1", "title": "session", "directory": str(home)}
            with patch("pathlib.Path.home", return_value=home), \
                 patch.object(tb, "_opencode_api", return_value=created):
                session = tb.create_session(cfg, "session")
            self.assertEqual(session["directory"], str(home))

    def test_create_session_rejects_empty_and_long_names_before_api(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with patch.object(tb, "_opencode_api") as api:
            for title in ("  \n ", "x" * (tb.SESSION_NAME_MAX_LENGTH + 1)):
                with self.assertRaises(ValueError):
                    tb.create_session(cfg, title)
        api.assert_not_called()

    def test_create_session_rejects_invalid_api_session_id(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with patch.object(tb, "_opencode_api", return_value={"id": "not-a-session"}):
            with self.assertRaisesRegex(RuntimeError, "invalid session ID"):
                tb.create_session(cfg, "valid title")

    def test_new_session_flow_creates_verifies_and_selects(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = None
        session = {"id": "ses_created1", "title": "Review task", "directory": str(pathlib.Path.home().resolve())}
        with patch.object(tb, "_send_reply_picker") as prompt, \
             patch.object(tb, "create_session", return_value=session) as create, \
             patch.object(tb, "_session_by_id", return_value=session) as verify, \
             patch.object(tb, "_set_active_session") as select, \
             patch.object(tb, "send_text") as send, patch.object(tb, "_send_keyboard") as keyboard:
            self.assertTrue(tb.handle_control_message(cfg, {}, "New session"))
            self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
            self.assertTrue(tb.handle_control_message(cfg, {}, "  Review   task  "))
        prompt.assert_called_once()
        create.assert_called_once_with(cfg, "Review task")
        verify.assert_called_once_with(cfg, "ses_created1")
        select.assert_called_once_with(session)
        self.assertIn("Review task", send.call_args.args[1])
        keyboard.assert_called_once_with(cfg)
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_unverified_session_is_not_selected(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        session = {"id": "ses_created1", "title": "Review task", "directory": str(pathlib.Path.home().resolve())}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session", return_value=session), \
             patch.object(tb, "_session_by_id", return_value=None), \
             patch.object(tb, "_set_active_session") as select, \
             patch.object(tb, "send_text") as send, patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Review task"))
        select.assert_not_called()
        send.assert_called_once()
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_new_session_cancel_does_not_create(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "send_text"), patch.object(tb, "_send_keyboard"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "Cancel"))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_model_picker_cancel_label_cancels_session_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session") as create, patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)
        send.assert_called_once()
        self.assertIn("cancelled", send.call_args.args[1].lower())

    def test_repeated_navigation_buttons_do_not_create_a_session(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        for text in ("Next", "Previous"):
            tb.ACTIVE_PICKER = "new-session-name"
            with self.subTest(text=text), patch.object(tb, "create_session") as create, \
                 patch.object(tb, "send_text") as send:
                self.assertTrue(tb.handle_control_message(cfg, {}, text))
                create.assert_not_called()
                send.assert_not_called()

    def test_cancel_alias_restores_keyboard_from_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "_send_keyboard") as keyboard, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        create.assert_not_called()
        keyboard.assert_called_once_with(cfg)
        send.assert_called_once()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_name_prompt_treats_model_alias_command_as_control(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "_models_from_api", return_value=[]), \
             patch.object(tb, "_read_models_cache", return_value=[]), \
             patch.object(tb, "_send_keyboard"), patch.object(tb, "send_text"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "/model"))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_command_precedence_routes_menu_and_session_commands_not_to_creation(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        for command in ("/menu", "/session", "/models", "/model", "/current", "/files", "/help", "/start"):
            tb.ACTIVE_PICKER = "new-session-name"
            with self.subTest(command=command), patch.object(tb, "create_session") as create, \
                 patch.object(tb, "_send_keyboard"), patch.object(tb, "send_text"), \
                 patch.object(tb, "_send_reply_picker"), patch.object(tb, "_invalidate_model_message_ref"), \
                 patch.object(tb, "_models_from_api", return_value=[]), patch.object(tb, "_read_models_cache", return_value=[]), \
                 patch.object(tb, "resolve_session", return_value=(None, "none")), \
                 patch.object(tb, "_session_by_id", return_value=None):
                self.assertTrue(tb.handle_control_message(cfg, {}, command))
            create.assert_not_called()

    def test_create_session_label_is_treated_as_name_from_session_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "sessions"
        with patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.CREATE_SESSION))
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_create_session_label_from_model_picker_starts_prompt_not_create(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "_send_reply_picker") as prompt, \
             patch.object(tb, "_invalidate_model_message_ref"):
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        create.assert_not_called()
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_new_session_alias_from_model_picker_starts_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_invalidate_model_message_ref"), \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_new_session_button_from_model_picker_starts_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_invalidate_model_message_ref"), \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_new_session_button_starts_name_prompt_from_provider_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "providers"
        with patch.object(tb, "_invalidate_model_message_ref"), \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.NEW_SESSION))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_start_command_cancels_pending_session_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "_send_keyboard"), patch.object(tb, "send_text") as send, \
             patch.object(tb, "create_session") as create:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/start"))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)
        send.assert_called_once()

    def test_start_help_control_is_not_used_as_a_session_title(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        for command in ("/help", "Help"):
            tb.ACTIVE_PICKER = "new-session-name"
            with self.subTest(command=command), patch.object(tb, "create_session") as create, \
                 patch.object(tb, "_send_keyboard"), patch.object(tb, "send_text"):
                self.assertTrue(tb.handle_control_message(cfg, {}, command))
                create.assert_not_called()
                self.assertIsNone(tb.ACTIVE_PICKER)

    def test_start_at_bot_alias_cancels_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "_send_keyboard"), patch.object(tb, "send_text"), \
             patch.object(tb, "create_session") as create:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/start@telecode_bot"))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_new_session_can_be_started_from_model_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_invalidate_model_message_ref"), \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, "New session"))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_cancel_label_closes_model_and_new_session_pickers(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        for picker_name in ("models", "new-session-name"):
            tb.ACTIVE_PICKER = picker_name
            with self.subTest(picker=picker_name), patch.object(tb, "_invalidate_model_message_ref"), \
                 patch.object(tb, "create_session") as create, patch.object(tb, "_send_keyboard"), \
                 patch.object(tb, "send_text"):
                self.assertTrue(tb.handle_control_message(cfg, {}, "Cancel"))
                create.assert_not_called()
                self.assertIsNone(tb.ACTIVE_PICKER)

    def test_create_session_alias_is_prompt_action_not_session_title(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.CREATE_SESSION))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_create_session_text_alias_starts_prompt_from_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "create_session") as create, \
             patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.CREATE_SESSION))
        create.assert_not_called()
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_menu_command_cancels_new_session_prompt_and_clears_picker_state(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        tb.SESSION_BUTTONS["stale"] = "ses_abcdef123456"
        with patch.object(tb, "_send_keyboard"), patch.object(tb, "create_session") as create:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/menu"))
        create.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)
        self.assertEqual(tb.SESSION_BUTTONS, {})

    def test_starting_session_picker_cancels_name_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "_send_reply_picker"), patch.object(tb, "_invalidate_model_message_ref"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "/session"))
        self.assertEqual(tb.ACTIVE_PICKER, "sessions")

    def test_session_creation_failure_keeps_name_prompt_active(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session", side_effect=RuntimeError("api down")), \
             patch.object(tb, "send_text") as send, patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Try again"))
        send.assert_called_once()
        prompt.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")

    def test_slash_command_during_session_name_prompt_does_not_create_session(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session") as create, patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/nonsense"))
        create.assert_not_called()
        send.assert_called_once()

    def test_main_keyboard_uses_labels_not_slash_commands(self):
        markup = tb._keyboard({})["keyboard"]
        buttons = {item["text"]: item for row in markup for item in row}
        self.assertEqual(buttons["New session"]["style"], "success")
        self.assertEqual(list(buttons), ["Current session", "New session", "Models", "Sessions", "Help"])

    def test_session_picker_button_caption_with_photo_is_consumed_as_control(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        sid = "ses_abcdefgh"
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [{"id": sid, "title": "work"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_BUTTONS.update({"work [cdefgh]": sid})
        msg = {"caption": "work [cdefgh]", "photo": [{"file_id": "photo-id"}]}
        with patch.object(tb, "_set_active_session") as set_session, \
             patch.object(tb, "send_text") as send, patch.object(tb, "_download_file") as download, \
             patch.object(tb.INJECT_Q, "put") as inject:
            self.assertTrue(tb.handle_control_message(cfg, msg, msg["caption"]))
        set_session.assert_not_called()
        send.assert_called_once()
        download.assert_not_called()
        inject.assert_not_called()

    def test_model_button_media_caption_is_not_silently_discarded(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "models"
        tb.MODEL_SELECTION.update(provider=0, page=0, labels={"Model One": 0},
                                  models={"Model One": ("p", "m1")})
        msg = {"caption": "Model One", "photo": [{"file_id": "photo-id"}]}
        with patch.object(tb, "send_text") as send, patch.object(tb, "_switch_session_model") as switch:
            self.assertTrue(tb.handle_control_message(cfg, msg, msg["caption"]))
        switch.assert_not_called()
        send.assert_called_once()

    def test_provider_and_model_picker_transition_posts_no_keyboard_reset_message(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        models = [{"id": "m1", "providerID": "provider", "name": "Model one"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_read_models_cache", return_value=models), \
             patch.object(tb, "_write_models_cache"), patch.object(tb, "api") as api, \
             patch.object(tb, "_send_picker_notice"), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "_load_models_message_ref", return_value='{"chat_id":"17","message_id":"42"}'), \
             patch.object(tb, "_set_models_message_ref"):
            tb._models_menu(cfg)
            self.assertEqual(api.call_count, 2)
            self.assertTrue(tb.handle_control_message(cfg, {}, "provider (1)"))
        # First picker is sent; provider transition edits the same message.
        methods = [call.args[1] for call in api.call_args_list]
        self.assertEqual(methods, ["editMessageText", "editMessageReplyMarkup",
                                   "editMessageText", "editMessageReplyMarkup"])
        self.assertEqual(methods.count("sendMessage"), 0)

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
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("is_persistent", markup)
        self.assertNotIn("input_field_placeholder", markup)
        self.assertEqual(markup["keyboard"][0][0]["text"], "test (1)")

    def test_model_close_returns_to_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_send_keyboard") as show, patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        show.assert_called_once_with(cfg)
        send.assert_not_called()
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_model_close_removes_saved_model_message_reference(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "_send_keyboard"), patch.object(tb, "_invalidate_model_message_ref") as save:
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_CLOSE))
        save.assert_called_once()

    def test_cancel_command_is_consumed_in_all_session_picker_variants(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        for picker in ("sessions", "models", "providers"):
            tb.ACTIVE_PICKER = picker
            with self.subTest(picker=picker), patch.object(tb, "create_session") as create, \
                 patch.object(tb, "send_text") as send, patch.object(tb, "_send_keyboard") as keyboard:
                self.assertTrue(tb.handle_control_message(cfg, {}, "Cancel"))
            create.assert_not_called()
            send.assert_not_called()
            keyboard.assert_called_once_with(cfg)
            self.assertIsNone(tb.ACTIVE_PICKER)

    def test_model_labels_are_not_consumed_when_no_model_picker_is_active(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        tb.MODEL_SELECTION["models"] = {"review": ("p", "review")}
        tb.MODEL_SELECTION["labels"] = {"review": 0}
        self.assertFalse(tb.handle_control_message(cfg, {}, "review"))

    def test_non_session_bracket_suffix_is_not_mistaken_for_stale_session_button(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        self.assertFalse(tb.handle_control_message(cfg, {}, "review the patch [feature123]"))

    def test_picker_reset_clears_previous_model_label_map(self):
        tb.ACTIVE_PICKER = "models"
        tb.MODEL_SELECTION["models"] = {"review": ("p", "review")}
        tb._restore_primary_controls()
        self.assertNotIn("models", tb.MODEL_SELECTION)

    def test_picker_failure_reissues_name_prompt_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        tb.ACTIVE_PICKER = "new-session-name"
        with patch.object(tb, "create_session", side_effect=RuntimeError("API down")), \
             patch.object(tb, "send_text"), patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Retry title"))
        self.assertEqual(tb.ACTIVE_PICKER, "new-session-name")
        prompt.assert_called_once()

    def test_startup_keyboard_has_model_selection_controls(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_configure_commands") as configure, patch.object(tb, "api") as api:
            tb._send_keyboard(cfg)
        import json
        markup = json.loads(api.call_args.args[2]["reply_markup"])
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("is_persistent", markup)
        self.assertNotIn("input_field_placeholder", markup)
        labels = [button["text"] for row in markup["keyboard"] for button in row]
        self.assertIn("Models", labels)
        self.assertFalse(any(label.startswith("/") for label in labels))
        configure.assert_not_called()

    def test_main_keyboard_uses_one_time_hint_without_remove_markup(self):
        markup = tb._keyboard({})
        self.assertFalse(markup["one_time_keyboard"])
        self.assertNotIn("is_persistent", markup)
        self.assertNotIn("remove_keyboard", markup)

    def test_new_session_picker_preserves_main_keyboard_and_one_time_hint(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "17"}
        with patch.object(tb, "_send_reply_picker") as picker:
            tb._begin_new_session(cfg)
        self.assertFalse(picker.call_args.kwargs.get("notify", True))
        self.assertEqual(picker.call_args.args[2][0], [{"text": "Cancel"}])
        self.assertEqual(len(picker.call_args.args[2]), 1)
    def test_session_picker_empty_results_do_not_reissue_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "list_sessions", return_value=[]), \
             patch.object(tb, "_send_reply_picker") as message, \
             patch.object(tb, "_send_keyboard") as keyboard:
            tb._send_session_picker(cfg)
        message.assert_called_once()
        self.assertEqual(message.call_args.args[2],
                         [[{"text": tb.NEW_SESSION}, {"text": "Open by ID"}], [{"text": "Cancel"}]])
        keyboard.assert_not_called()

    def test_files_command_exits_model_picker_and_restores_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "models"
        with patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", None)), \
             patch.object(tb, "send_text"), patch.object(tb, "_send_keyboard") as keyboard:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Files"))
        keyboard.assert_called_once_with(cfg)
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
        self.assertIn({"command": "newsession", "description": "Create and select a session"}, commands)
        self.assertIn({"command": "files", "description": "List received files"}, commands)
        self.assertIn({"command": "start", "description": "Show TeleCode controls"}, commands)
        self.assertIn({"command": "current", "description": "Show the active session"}, commands)

    def test_cancel_button_closes_session_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        with patch.object(tb, "_hide_picker_keyboard") as hide, patch.object(tb, "_send_keyboard") as keyboard:
            handled = tb.handle_control_message(cfg, {}, "Cancel")
        self.assertTrue(handled)
        self.assertIsNone(tb.ACTIVE_PICKER)
        hide.assert_not_called()
        keyboard.assert_called_once_with(cfg)

    def test_menu_command_resets_picker_state_and_restores_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [{"id": "ses_abcdef1", "title": "stale"}]
        tb.SESSION_BUTTONS.clear()
        tb.SESSION_BUTTONS["stale"] = "ses_abcdef1"
        with patch.object(tb, "_hide_picker_keyboard"), patch.object(tb, "_send_keyboard") as show:
            self.assertTrue(tb.handle_control_message(cfg, {}, "/menu"))
        show.assert_called_once_with(cfg)
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
        with patch.object(tb, "_hide_picker_keyboard"), \
             patch.object(tb, "_send_keyboard") as keyboard, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Help"))
        self.assertIsNone(tb.ACTIVE_PICKER)
        send.assert_called_once()
        keyboard.assert_called_once()
        self.assertIn("Commands", send.call_args.args[1])

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

    def test_orphaned_pagination_text_is_not_consumed_as_control(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = None
        with patch.object(tb, "send_text") as send:
            self.assertFalse(tb.handle_control_message(cfg, {}, "Next"))
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
             patch.object(tb, "send_text") as send, patch.object(tb, "_send_keyboard"):
            self.assertTrue(tb.handle_control_message(cfg, {}, "Model"))
        switch.assert_not_called()
        send.assert_called_once()

    def test_session_label_cannot_select_outside_active_page(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{n:06d}", "title": f"session {n}"} for n in range(45)]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), patch.object(tb, "api"), \
             patch.object(tb, "send_text"), patch.object(tb, "_set_active_session") as select:
            tb._send_session_picker(cfg, page=0, sessions=sessions)
            handled = tb.handle_control_message(cfg, {}, "session 40")
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

    def test_inject_rejects_queued_target_from_another_agent(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1", "TELECODE_AGENT": "codex"}
        rec = {"update_id": 11, "text": "hello", "session_id": "01234567-89ab-cdef-0123-456789abcdef",
               "agent": "cursor"}
        with patch.object(tb, "resolve_session") as resolve, \
             patch.object(tb, "_try_prompt") as prompt, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.inject_record(cfg, rec))
        resolve.assert_not_called()
        prompt.assert_not_called()
        send.assert_called_once()

    def test_inject_fails_closed_for_legacy_queued_target_without_agent(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1", "TELECODE_AGENT": "claude-code"}
        rec = {"update_id": 12, "text": "hello", "session_id": "01234567-89ab-cdef-0123-456789abcdef"}
        with patch.object(tb, "resolve_session") as resolve, \
             patch.object(tb, "_try_prompt") as prompt, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.inject_record(cfg, rec))
        resolve.assert_not_called()
        prompt.assert_not_called()
        send.assert_called_once()

    def test_inject_accepts_claude_alias_for_claude_code_queued_target(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1", "TELECODE_AGENT": "claude"}
        rec = {"update_id": 13, "text": "hello", "session_id": "01234567-89ab-cdef-0123-456789abcdef",
               "agent": "claude-code"}
        with tempfile.TemporaryDirectory() as temp, \
             patch.object(tb, "STATE", pathlib.Path(temp) / "wake-session.txt"), \
             patch.object(tb, "resolve_session", return_value=(rec["session_id"], "active")), \
             patch.object(tb, "_session_by_id", return_value={"id": rec["session_id"]}), \
             patch.object(tb, "_try_prompt", return_value=True) as prompt:
            self.assertTrue(tb.inject_record(cfg, rec))
        prompt.assert_called_once_with(cfg, rec["session_id"], "hello", "steer")

    def test_models_cache_roundtrip_is_private(self):
        models = [
            {"id": "openai/gpt", "providerID": "openrouter", "name": "GPT"},
            {"id": "gemini", "providerID": "google", "name": "Gemini"},
        ]
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "models-cache.json"
            with patch.object(tb, "MODELS_CACHE", cache):
                tb._write_models_cache(models)
                if os.name != "nt":
                    self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
                self.assertEqual(tb._read_models_cache(), models)

    def test_models_cache_rejects_corrupt_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = pathlib.Path(temp) / "models-cache.json"
            cache.write_text("{not json")
            with patch.object(tb, "MODELS_CACHE", cache):
                self.assertEqual(tb._read_models_cache(), [])

    def test_models_cache_is_separate_per_agent(self):
        cursor = [{"id": "cursor-model", "providerID": "Cursor", "name": "Cursor model"}]
        codex = [{"id": "codex-model", "providerID": "openai", "name": "Codex model"}]
        with tempfile.TemporaryDirectory() as temp, patch.object(
                tb, "MODELS_CACHE", pathlib.Path(temp) / "models-cache.json"):
            tb._write_models_cache(cursor, {"TELECODE_AGENT": "cursor"})
            tb._write_models_cache(codex, {"TELECODE_AGENT": "codex"})
            self.assertEqual(tb._read_models_cache({"TELECODE_AGENT": "cursor"}), cursor)
            self.assertEqual(tb._read_models_cache({"TELECODE_AGENT": "codex"}), codex)

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

    def test_session_picker_does_not_duplicate_session_list_in_message(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abc1234567", "title": "fix_auth.v2"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg)
        payload = api.call_args.args[2]
        self.assertEqual(payload["parse_mode"], "HTML")
        self.assertIn("Choose a session", payload["text"])
        self.assertNotIn("fix_auth.v2", payload["text"])
        self.assertNotIn("ses_abc1234567", payload["text"])
        markup = __import__("json").loads(payload["reply_markup"])
        self.assertEqual(markup["keyboard"][0][0]["text"], "1. fix_auth.v2")

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
        self.assertIn("Choose a session", api.call_args.args[2]["text"])
        self.assertNotIn("A < B", api.call_args.args[2]["text"])

    def test_session_listing_returns_empty_on_api_failure(self):
        cfg = {"TG_BOT_TOKEN": "unused"}
        with patch.object(tb, "_session_items", side_effect=RuntimeError("api down")) as listing:
            result = tb.list_sessions(cfg)
        self.assertEqual(result, [])
        self.assertEqual(listing.call_count, 1)

    def test_session_listing_returns_sessions_from_any_directory(self):
        cfg = {"TG_BOT_TOKEN": "unused"}
        items = [
            {"id": "ses_aaaaaa", "directory": str(pathlib.Path.home()), "time": {}},
            {"id": "ses_bbbbbb", "directory": "/some/other/project", "time": {}},
        ]
        with patch.object(tb, "_session_items", return_value=items) as listing:
            result = tb.list_sessions(cfg)
        self.assertEqual([item["id"] for item in result], ["ses_aaaaaa", "ses_bbbbbb"])
        self.assertEqual(listing.call_count, 1)

    def test_session_picker_displays_only_the_selected_page(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(45)]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg, page=1)
        payload = api.call_args.args[2]
        keyboard = __import__("json").loads(payload["reply_markup"])["keyboard"]
        labels = [row[0]["text"] for row in keyboard if row and row[0]["text"] not in
                  ("Previous", "Next", "Cancel", tb.NEW_SESSION, "Open by ID")]
        self.assertEqual(len(labels), 20)
        self.assertEqual(labels[0], "21. session 20")
        self.assertEqual(labels[-1], "40. session 39")
        self.assertNotIn("ses_", payload["text"])
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_session_page_change_reuses_one_session_snapshot(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": f"ses_{i:06d}", "title": f"session {i}"} for i in range(40)]
        tb.SESSION_SNAPSHOT = []
        tb.SESSION_BUTTONS.clear()
        with patch.object(tb, "list_sessions", return_value=sessions) as listing, \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "discover_session", return_value=""), \
             patch.object(tb, "api"), patch.object(tb, "_send_reply_picker"):
            tb.ACTIVE_PICKER = "sessions"
            tb.SESSION_SNAPSHOT = list(sessions)
            self.assertTrue(tb.handle_control_message(cfg, {}, "Next"))
        listing.assert_not_called()
        self.assertEqual(tb.SESSION_PAGE, 1)

    def test_menu_button_without_slash_restores_main_keyboard(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        for picker in (None, "sessions", "models", "providers", "new-session-name"):
            tb.ACTIVE_PICKER = picker
            with self.subTest(picker=picker), \
                 patch.object(tb, "_send_keyboard") as keyboard, \
                 patch.object(tb, "send_text") as send:
                self.assertTrue(tb.handle_control_message(cfg, {}, "Menu"))
            self.assertTrue(keyboard.called)
            send.assert_not_called()

    def test_keyboard_button_ignores_unicode_variation_selector(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        with patch.object(tb, "_send_session_picker") as picker:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Sessions\ufe0f"))
        picker.assert_called_once()

    def test_keyboard_labels_are_english(self):
        buttons = [button["text"] for row in tb._keyboard({})["keyboard"] for button in row]
        self.assertEqual(buttons, ["Current session", "New session", "Models", "Sessions", "Help"])

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
        models = [{"id": f"id-{n}", "providerID": "p", "name": f"Model {n}"} for n in range(45)]
        with patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_load_models_message_ref", return_value='{"chat_id":"1","message_id":"42"}'), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")), \
             patch.object(tb, "_read_models_cache", return_value=models):
            tb._models_menu(cfg, provider_index=0, models_snapshot=models)
            self.assertTrue(tb.handle_control_message(cfg, {}, "Next"))
            self.assertEqual(tb.MODEL_SELECTION["page"], 1)
            self.assertEqual(set(tb.MODEL_SELECTION["labels"].values()), set(range(20, 40)))
            self.assertTrue(tb.handle_control_message(cfg, {}, "Previous"))
            self.assertEqual(tb.MODEL_SELECTION["page"], 0)
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_BACK))
            self.assertIsNone(tb.MODEL_SELECTION["provider"])
            self.assertIn("p (45)", tb.MODEL_SELECTION["labels"])

    def test_model_page_has_twenty_items_and_cancel_closes_picker(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": f"id-{n}", "providerID": "p", "name": f"Model {n}"} for n in range(25)]
        with patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_load_models_message_ref", return_value=""), \
             patch.object(tb, "_current_model", return_value=""), \
             patch.object(tb, "resolve_session", return_value=("ses_abcdefgh", "active")):
            tb._models_menu(cfg, provider_index=0, models_snapshot=models)
            rows = picker.call_args.args[2]
            self.assertEqual(sum(1 for row in rows if row[0]["text"].startswith("Model ")), 20)
            self.assertEqual(rows[-2][0]["text"], "Next")
            self.assertTrue(tb.handle_control_message(cfg, {}, "Cancel"))
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_provider_page_cancels_and_model_page_returns_to_providers(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        models = [{"id": "model-id", "providerID": "provider", "name": "Model"}]
        with patch.object(tb, "_models_from_api", return_value=models), \
             patch.object(tb, "_write_models_cache"), \
             patch.object(tb, "_send_reply_picker") as picker, \
             patch.object(tb, "_load_models_message_ref", return_value=""), \
             patch.object(tb, "_read_models_cache", return_value=models), \
             patch.object(tb, "_current_model", return_value=""):
            tb._models_menu(cfg)
            provider_labels = [button["text"] for row in picker.call_args.args[2] for button in row]
            self.assertIn(tb.MODEL_CLOSE, provider_labels)
            self.assertNotIn(tb.MODEL_BACK, provider_labels)
            self.assertTrue(tb.handle_control_message(cfg, {}, "provider (1)"))
            model_labels = [button["text"] for row in picker.call_args.args[2] for button in row]
            self.assertIn(tb.MODEL_BACK, model_labels)
            self.assertIn(tb.MODEL_CLOSE, model_labels)
            self.assertTrue(tb.handle_control_message(cfg, {}, tb.MODEL_BACK))
        self.assertEqual(tb.ACTIVE_PICKER, "providers")

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
            label = next(label for label in tb.SESSION_BUTTONS if label.startswith("1."))
            self.assertTrue(tb.handle_control_message(cfg, {}, label))
        select.assert_called_once_with(sessions[0])

    def test_open_by_id_action_validates_and_selects_available_session(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sid = "ses_abcdef123456"
        session = {"id": sid, "title": "opened directly"}
        tb.ACTIVE_PICKER = "sessions"
        tb.SESSION_SNAPSHOT = [session]
        with patch.object(tb, "_send_reply_picker") as prompt:
            self.assertTrue(tb.handle_control_message(cfg, {}, "Open by ID"))
        self.assertEqual(tb.ACTIVE_PICKER, "session-id")
        self.assertIn("Open a session by ID", prompt.call_args.args[1])

        with patch.object(tb, "_session_by_id", return_value=session) as lookup, \
             patch.object(tb, "_set_active_session") as select, \
             patch.object(tb, "send_text") as send, patch.object(tb, "_send_keyboard") as keyboard:
            self.assertTrue(tb.handle_control_message(cfg, {}, sid))
        lookup.assert_called_once_with(cfg, sid)
        select.assert_called_once_with(session)
        send.assert_called_once()
        keyboard.assert_called_once_with(cfg)
        self.assertIsNone(tb.ACTIVE_PICKER)

    def test_open_by_id_rejects_unavailable_id_without_leaving_prompt(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        tb.ACTIVE_PICKER = "session-id"
        with patch.object(tb, "_session_by_id", return_value=None) as lookup, \
             patch.object(tb, "send_text") as send:
            self.assertTrue(tb.handle_control_message(cfg, {}, "ses_notfound"))
        lookup.assert_called_once_with(cfg, "ses_notfound")
        send.assert_called_once()
        self.assertEqual(tb.ACTIVE_PICKER, "session-id")

    def test_module_has_no_emoji_in_ui_strings(self):
        sources = [BRIDGE.read_text(encoding="utf-8")]
        sources.extend(
            p.read_text(encoding="utf-8")
            for p in sorted(BRIDGE.parent.glob("telegram_bridge/*.py"))
        )
        emoji = [ch for source in sources for ch in source if ord(ch) >= 0x1F000]
        self.assertEqual(emoji, [])

    @unittest.skip("The legacy terminal menu was removed; setup_cli.py owns the interactive setup menu.")
    def test_menu_exits_cleanly_on_q(self):
        pass

    def test_no_arguments_without_tty_prints_usage(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["TELEGRAM_BRIDGE_HOME"] = tmp
            run = subprocess.run([sys.executable, str(BRIDGE)], stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, check=False, env=env)
        self.assertEqual(run.returncode, 2)
        self.assertIn("menu", run.stderr)

    def test_listener_pid_file_is_removed_only_for_own_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = pathlib.Path(tmp) / "listener.pid"
            with patch.object(tb, "PID", pidfile):
                pidfile.write_text(str(os.getpid()))
                tb._remove_pid_file()
                self.assertFalse(pidfile.exists())
                pidfile.write_text("1")
                tb._remove_pid_file()
                self.assertTrue(pidfile.exists())

    def test_session_picker_header_is_short_and_separated_from_rows(self):
        cfg = {"TG_BOT_TOKEN": "unused", "TG_CHAT_ID": "1"}
        sessions = [{"id": "ses_abcdefgh", "title": "work"}]
        with patch.object(tb, "list_sessions", return_value=sessions), \
             patch.object(tb, "_active_session_id", return_value=""), \
             patch.object(tb, "api") as api:
            tb._send_session_picker(cfg)
        body = api.call_args.args[2]["text"]
        self.assertEqual(body, "<b>Choose a session</b>\nTap a button to select the destination for your Telegram messages.")


if __name__ == "__main__":
    unittest.main()
