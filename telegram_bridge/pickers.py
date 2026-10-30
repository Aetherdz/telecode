"""Pickers: session, model, and control-message keyboard flows."""
import json
import os
import re
import time
import urllib.parse

import telegram_bridge as tg


def _send_picker_notice(cfg, text):
    """Compatibility hook; avoid creating another chat message for transitions."""
    return None


def _invalidate_model_message_ref():
    try:
        path = tg.MODELS_CACHE.with_name("models-message.json")
        path.unlink(missing_ok=True)
    except OSError as e:
        tg.log(f"[{tg.ts()}] could not invalidate model-picker reference: {e!r}", flush=True)


def _hide_picker_keyboard(cfg):
    """Compatibility shim retained for callers; do not re-send a keyboard."""
    return None


def session_title(session):
    title = str((session or {}).get("title") or "Untitled").replace("\n", " ").strip()
    return title[:36] or "Untitled"


def session_label(session):
    return f"{tg.session_title(session)} [{str((session or {}).get('id') or '')}]"


def _session_buttons(sessions):
    """Use short numbered labels; keep raw session IDs out of the keyboard."""
    labels = {}
    for index, session in enumerate(sessions, start=1):
        title = tg.session_title(session)
        sid = str(session.get("id") or "")
        labels[sid] = f"{index}. {title}"
    return labels


def _send_session_picker(cfg, page=0, sessions=None):
    sessions = tg.list_sessions(cfg) if sessions is None else sessions
    if not sessions:
        tg.SESSION_SNAPSHOT = []
        tg.SESSION_BUTTONS.clear()
        tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
        tg.ACTIVE_PICKER = "sessions"
        text = "No OpenCode sessions were found. Create one, or check that the OpenCode service is running."
        tg._send_reply_picker(cfg, text,
                              [[{"text": tg.NEW_SESSION}, {"text": "Open by ID"}],
                               [{"text": "Cancel"}]], notify=False)
        return
    tg.SESSION_SNAPSHOT = list(sessions)
    tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
    tg.SESSION_PAGE = min(max(0, page), (len(sessions) - 1) // tg.SESSION_PAGE_SIZE)
    start = tg.SESSION_PAGE * tg.SESSION_PAGE_SIZE
    visible = sessions
    labels = tg._session_buttons(sessions)
    rows = [[{"text": labels[str(s.get("id") or "")]}]
            for s in visible[start:start + tg.SESSION_PAGE_SIZE]]
    rows.append([{"text": tg.NEW_SESSION}, {"text": "Open by ID"}])
    tg.SESSION_BUTTONS.clear()
    tg.SESSION_BUTTONS.update({labels[str(s.get("id") or "")]: str(s.get("id") or "")
                               for s in visible[start:start + tg.SESSION_PAGE_SIZE]})
    tg.ACTIVE_PICKER = "sessions"
    nav = []
    if tg.SESSION_PAGE > 0:
        nav.append({"text": "Previous"})
    if start + tg.SESSION_PAGE_SIZE < len(sessions):
        nav.append({"text": "Next"})
    if nav:
        rows.append(nav)
    rows.append([{"text": "Cancel"}])
    text = "<b>Choose a session</b>\nTap a button to select the destination for your Telegram messages."
    tg._send_reply_picker(cfg, text, rows, notify=False)


def _begin_new_session(cfg):
    if tg.ACTIVE_PICKER in ("models", "providers"):
        tg._invalidate_model_message_ref()
    tg.ACTIVE_PICKER = "new-session-name"
    tg.SESSION_SNAPSHOT = []
    tg.SESSION_BUTTONS.clear()
    tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
    tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)
    tg._send_reply_picker(
        cfg,
        f"<b>New OpenCode session</b>\nSend the session name as your next message (up to {tg.SESSION_NAME_MAX_LENGTH} characters). Send Cancel to stop.",
        [[{"text": "Cancel"}]],
        notify=False,
    )


def _begin_session_id(cfg):
    tg.ACTIVE_PICKER = "session-id"
    tg._send_reply_picker(
        cfg,
        "<b>Open a session by ID</b>\nSend the session ID (for example, <code>ses...</code>). Only an available session in this OpenCode workspace can be selected.",
        [[{"text": "Cancel"}]],
        notify=False,
    )


def _restore_primary_controls():
    """Discard temporary picker state before routing to another control."""
    tg.ACTIVE_PICKER = None
    tg.SESSION_BUTTONS.clear()
    tg.SESSION_SNAPSHOT.clear()
    tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
    tg.MODEL_SELECTION.pop("models", None)
    tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)


def _send_reply_picker(cfg, text, rows, notify=True):
    params = {
        "chat_id": cfg["TG_CHAT_ID"], "text": text, "parse_mode": "HTML",
        "reply_markup": json.dumps({
            "keyboard": tg._style_keyboard(rows),
            "resize_keyboard": True,
            "one_time_keyboard": False,
        }, ensure_ascii=False),
    }
    try:
        result = tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    except Exception as e:
        tg.log(f"[{tg.ts()}] formatted session picker failed; retrying as plain text: {e!r}", flush=True)
        params["text"] = tg._plain_fallback(text)
        params.pop("parse_mode", None)
        result = tg.api(cfg["TG_BOT_TOKEN"], "sendMessage", params, timeout=15)
    if notify and result and result.get("result", {}).get("message_id"):
        tg._set_models_message_ref({"chat_id": cfg["TG_CHAT_ID"],
                                 "message_id": result["result"]["message_id"]})


def _callback_message_ref(cb):
    message = cb.get("message") or {}
    chat_id = str(((message.get("chat") or {}).get("id")) or "")
    message_id = str(message.get("message_id") or "")
    if not chat_id or not message_id:
        return ""
    return json.dumps({"chat_id": chat_id, "message_id": message_id})


def _load_models_message_ref():
    try:
        value = json.loads(tg.MODELS_CACHE.with_name("models-message.json").read_text(encoding="utf-8"))
        expires = int(value.get("expires", 0))
        if not value.get("chat_id") or not value.get("message_id") or expires < int(time.time()):
            return ""
        return json.dumps(value)
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def _models_from_api(cfg):
    data = tg._opencode_api(cfg, "get", "/api/model", timeout=45)
    items = data.get("data") if isinstance(data, dict) else data
    out = []
    for model in items or []:
        if not isinstance(model, dict):
            continue
        mid = str(model.get("modelID") or model.get("id") or "").strip()
        provider = str(model.get("providerID") or "").strip()
        if not mid or not provider:
            continue
        out.append({"id": mid, "providerID": provider,
                    "name": str(model.get("name") or mid)})
    return out


def _write_models_cache(models):
    temp = tg.MODELS_CACHE.with_name(f".models-cache.{os.getpid()}.tmp")
    tg.MODELS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(json.dumps({"saved": int(time.time()), "models": models},
                               ensure_ascii=False), encoding="utf-8")
    os.chmod(temp, 0o600)
    os.replace(temp, tg.MODELS_CACHE)


def _read_models_cache():
    try:
        payload = json.loads(tg.MODELS_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return []
    return [m for m in models if isinstance(m, dict) and m.get("id") and m.get("providerID")]


def _group_models(models):
    groups = {}
    for model in models:
        groups.setdefault(str(model["providerID"]), []).append(model)
    return {p: sorted(items, key=lambda m: str(m.get("name", "")).lower())
            for p, items in groups.items()}


def _ordered_providers(groups):
    return sorted(groups, key=lambda p: (-len(groups[p]), p))


def _current_model(cfg, sid):
    if not sid:
        return ""
    try:
        data = tg._opencode_api(cfg, "get",
                                f"/api/session/{urllib.parse.quote(sid, safe='')}", timeout=20)
    except Exception:
        return ""
    info = data.get("data") if isinstance(data, dict) else data
    model = (info or {}).get("model") or {}
    return str(model.get("id") or "")


def _models_menu(cfg, provider_index=None, page=0, models_snapshot=None):
    """Show model-provider and model pages in Telegram's bottom reply keyboard."""
    if models_snapshot is not None:
        models = models_snapshot
    else:
        try:
            models = tg._models_from_api(cfg)
            if models:
                tg._write_models_cache(models)
        except Exception as e:
            tg.log(f"[{tg.ts()}] model listing failed: {e!r}", flush=True)
            models = tg._read_models_cache()
    if not models:
        tg.ACTIVE_PICKER = None
        tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
        tg.send_text(cfg, "Unable to load models from OpenCode. Check that the service is running, then send /models again.")
        tg._send_keyboard(cfg, "Model list unavailable. Use Models or /models to retry.")
        return
    groups = tg._group_models(models)
    providers = tg._ordered_providers(groups)
    try:
        provider_index = None if provider_index is None else int(provider_index)
        page = int(page)
    except (TypeError, ValueError):
        provider_index, page = None, 0
    if provider_index is not None and not 0 <= provider_index < len(providers):
        provider_index = 0
    current = ""
    if provider_index is not None:
        sid, _ = tg.resolve_session(cfg)
        current = tg._current_model(cfg, sid)
    if provider_index is None:
        tg.ACTIVE_PICKER = "providers"
        tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)
        header = "<b>Choose a model provider</b>"
        if current:
            header += f"\nCurrent model: <code>{tg._html_escape(current)}</code>"
        rows = []
        provider_labels = {}
        reserved = {tg.MODEL_CLOSE, tg.MODEL_BACK, tg.MODEL_PREVIOUS, tg.MODEL_NEXT,
                    "Next", "Previous", "Sessions", "Models", "Help",
                    "Current session", "Cancel", "Menu", "Show menu", "Files",
                    "/menu", "/session", "/models", "/model", "/help"}
        for index, provider in enumerate(providers):
            base = f"{provider} ({len(groups[provider])})"
            label = base
            suffix = 2
            while label in provider_labels or label in reserved:
                label = f"{base} [{suffix}]"
                suffix += 1
            provider_labels[label] = index
            rows.append([{"text": label}])
        rows.append([{"text": tg.MODEL_CLOSE}])
        tg.MODEL_SELECTION.update(provider=None, page=0, labels=provider_labels)
        header += "\nUse /menu to restore the primary keyboard."
        current_ref = tg._load_models_message_ref()
        result = None
        if not tg._edit_reply_picker(cfg, current_ref, header, rows, "Choose a model provider"):
            result = tg._send_reply_picker(cfg, header, rows)
        tg._remember_reply_picker_message(result)
        return
    provider = providers[provider_index]
    tg.ACTIVE_PICKER = "models"
    items = groups[provider]
    pages = max(1, (len(items) + tg.MODELS_PAGE_SIZE - 1) // tg.MODELS_PAGE_SIZE)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = min(max(0, page), pages - 1)
    tg.MODEL_PAGE_STATE.update(provider_index=provider_index, page=page)
    start = page * tg.MODELS_PAGE_SIZE
    rows = []
    seen = {}
    labels = {}
    reserved = {tg.MODEL_CLOSE, tg.MODEL_BACK, tg.MODEL_PREVIOUS, tg.MODEL_NEXT,
                "Next", "Previous", "Sessions", "Models", "Help",
                "Current session", "Cancel", "Menu", "Show menu", "Files",
                "/menu", "/session", "/models", "/model", "/help"}
    for offset, model in enumerate(items[start:start + tg.MODELS_PAGE_SIZE]):
        base = str(model.get("name") or model["id"]).replace("\n", " ").replace("\r", " ")[:28]
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base} [{start + offset + 1}]"
        if current and model["id"] == current:
            name = f"Current: {name}"
        name = name[:64]
        if name in labels or name in reserved:
            name = f"{base} [{start + offset + 1}]"[:64]
        while name in labels or name in reserved:
            name = f"{name[:56]} [{start + offset + 1}]"[:64]
        labels[name] = start + offset
        rows.append([{"text": name}])
    nav = []
    if page > 0:
        nav.append({"text": "Previous"})
    if page + 1 < pages:
        nav.append({"text": "Next"})
    if nav:
        rows.append(nav)
    rows.append([{"text": tg.MODEL_BACK}, {"text": tg.MODEL_CLOSE}])
    tg.MODEL_SELECTION.update(provider=provider_index, page=page, labels=labels)
    tg.MODEL_SELECTION["models"] = {
        name: (items[index].get("providerID"), items[index].get("id"))
        for name, index in labels.items()
    }
    text = f"<b>{tg._html_escape(provider)}</b> — Select a model ({page + 1}/{pages})"
    if current:
        text += f"\nCurrent model: <code>{tg._html_escape(current)}</code>"
    text += "\nUse /menu to restore the primary keyboard."
    current_ref = tg._load_models_message_ref()
    result = None
    if not tg._edit_reply_picker(cfg, current_ref, text, rows, "Choose a model"):
        result = tg._send_reply_picker(cfg, text, rows)
    tg._remember_reply_picker_message(result)


def _remember_reply_picker_message(result):
    message = result.get("result") if isinstance(result, dict) else None
    message_id = message.get("message_id") if isinstance(message, dict) else None
    chat_id = (message.get("chat") or {}).get("id") if isinstance(message, dict) else None
    if message_id and chat_id:
        tg._set_models_message_ref({"chat_id": chat_id, "message_id": message_id})


def _edit_reply_picker(cfg, message_ref, text, rows, placeholder):
    try:
        ref = json.loads(message_ref or "{}")
    except (TypeError, ValueError):
        return False
    chat_id, message_id = str(ref.get("chat_id") or ""), str(ref.get("message_id") or "")
    if not chat_id or not message_id:
        return False
    markup = json.dumps({
        "keyboard": rows, "resize_keyboard": True,
        "one_time_keyboard": False,
    }, ensure_ascii=False)
    try:
        tg.api(cfg["TG_BOT_TOKEN"], "editMessageText", {
            "chat_id": chat_id, "message_id": message_id, "text": text,
            "parse_mode": "HTML",
        }, timeout=15)
        tg.api(cfg["TG_BOT_TOKEN"], "editMessageReplyMarkup", {
            "chat_id": chat_id, "message_id": message_id,
            "reply_markup": markup,
        }, timeout=15)
        tg._set_models_message_ref({"chat_id": chat_id, "message_id": message_id})
        return True
    except Exception as e:
        tg.log(f"[{tg.ts()}] picker message edit failed; sending replacement: {e!r}", flush=True)
        try:
            tg.api(cfg["TG_BOT_TOKEN"], "editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}),
            }, timeout=15)
        except Exception:
            pass
        return False


def _set_models_message_ref(ref):
    try:
        temp = tg.MODELS_CACHE.with_name(f".models-message.{os.getpid()}.tmp")
        payload = json.dumps({"chat_id": str(ref["chat_id"]),
                              "message_id": str(ref["message_id"]),
                              "expires": int(time.time()) + 23 * 3600})
        temp.write_text(payload, encoding="utf-8")
        os.chmod(temp, 0o600)
        tg.MODELS_CACHE.with_name("models-message.json").parent.mkdir(parents=True, exist_ok=True)
        os.replace(temp, tg.MODELS_CACHE.with_name("models-message.json"))
    except OSError as e:
        tg.log(f"[{tg.ts()}] could not save model-picker message reference: {e!r}", flush=True)


def _switch_session_model(cfg, model):
    sid, how = tg.resolve_session(cfg)
    if not sid:
        tg.send_text(cfg, "No active session is available for model switching.")
        return
    model_name = tg._html_escape(model.get("name") or model.get("id") or "model")
    provider = tg._html_escape(model.get("providerID") or "")
    session_name = tg._html_escape(tg.session_title(tg._session_by_id(cfg, sid) or {"id": sid}))
    tg._opencode_api(
        cfg, "post", f"/api/session/{urllib.parse.quote(sid, safe='')}/model",
        {"model": {"id": model["id"], "providerID": model["providerID"]}}, timeout=30)
    tg.log(f"[{tg.ts()}] model switch sid={sid} ({how}) -> {model['providerID']}/{model['id']}", flush=True)
    tg._send_picker_notice(cfg, f"<b>Model switched</b>\n{model_name} (<code>{provider}</code>)\nSession: {session_name}")


def handle_callback(cfg, cb):
    """Handle inline-keyboard callbacks (legacy model messages only)."""
    data = str(cb.get("data") or "")
    callback_id = str(cb.get("id") or "")
    if callback_id:
        try:
            tg.api(cfg["TG_BOT_TOKEN"], "answerCallbackQuery",
                   {"callback_query_id": callback_id}, timeout=10)
        except Exception as e:
            tg.log(f"[{tg.ts()}] answerCallbackQuery failed: {e!r}", flush=True)
    message_ref = tg._callback_message_ref(cb)
    parts = data.split(":")
    try:
        if len(parts) == 3 and parts[1] == "p":
            tg._models_menu(cfg, provider_index=int(parts[2]), models_snapshot=tg._read_models_cache())
            return True
        if len(parts) == 4 and parts[1] == "l":
            tg._models_menu(cfg, int(parts[2]), int(parts[3]), models_snapshot=tg._read_models_cache())
            return True
        if len(parts) == 4 and parts[1] == "s":
            groups = tg._group_models(tg._read_models_cache())
            providers = tg._ordered_providers(groups)
            provider_index, model_index = int(parts[2]), int(parts[3])
            if not (0 <= provider_index < len(providers)):
                tg.send_text(cfg, "This model list expired. Send /models to open a fresh list.")
                return True
            items = groups[providers[provider_index]]
            if not (0 <= model_index < len(items)):
                tg.send_text(cfg, "This model list expired. Send /models to open a fresh list.")
                return True
            try:
                tg._switch_session_model(cfg, items[model_index])
            except Exception as e:
                tg.log(f"[{tg.ts()}] model switch failed: {e!r}", flush=True)
                tg.send_text(cfg, f"Model switch failed: {tg._html_escape(str(e)[:140])}", parse_mode="HTML")
            else:
                tg._invalidate_model_message_ref()
            return True
    except (TypeError, ValueError):
        return False
    return False


def handle_control_message(cfg, msg, text):
    """Handle Telegram keyboard commands before normal agent injection."""
    cmd = (text or "").strip().replace("\ufe0e", "").replace("\ufe0f", "").strip()
    if cmd.startswith("/") and "@" in cmd:
        cmd = cmd.split("@", 1)[0]

    if tg.ACTIVE_PICKER == "session-id":
        if cmd == "Cancel":
            snapshot = list(tg.SESSION_SNAPSHOT)
            page = tg.SESSION_PAGE
            if snapshot:
                tg._send_session_picker(cfg, page, snapshot)
            else:
                tg._restore_primary_controls()
                tg._send_keyboard(cfg)
            return True
        if cmd in ("/session", "Sessions", "/models", "/model", "Models",
                   "/current", "Current session", "/help", "Help", "/start",
                   tg.NEW_SESSION, tg.CREATE_SESSION, "/newsession"):
            tg._restore_primary_controls()
            return tg.handle_control_message(cfg, msg, cmd)
        if msg.get("photo") or msg.get("document"):
            tg.send_text(cfg, "Send a text session ID, or Cancel. Attachments are not accepted here.")
            return True
        session = tg._session_by_id(cfg, cmd)
        if not session:
            tg.send_text(cfg, "That session ID is invalid or unavailable in this OpenCode workspace. Check the ID and try again, or Cancel.")
            return True
        tg._set_active_session(session)
        tg._restore_primary_controls()
        tg.send_text(cfg, f"<b>Target session:</b> {tg._html_escape(tg.session_title(session))}\n<b>Session ID:</b> <code>{tg._html_escape(session['id'])}</code>", parse_mode="HTML")
        tg._send_keyboard(cfg)
        return True

    # Handle the name-entry state first so ordinary text is never mistaken for a
    # command and create-session actions can never become the title themselves.
    if tg.ACTIVE_PICKER == "new-session-name":
        if cmd in ("Cancel", tg.MODEL_CLOSE):
            tg._restore_primary_controls()
            tg._send_keyboard(cfg)
            tg.send_text(cfg, "Session creation cancelled.")
            return True
        if cmd in ("/menu", "Menu", "Show menu"):
            tg._restore_primary_controls()
            tg._send_keyboard(cfg)
            return True
        if cmd in (tg.NEW_SESSION, tg.CREATE_SESSION, "/newsession"):
            tg._begin_new_session(cfg)
            return True
        if cmd in ("Next", "Previous"):
            return True
        controls = {
            "/session", "Sessions", "/models", "/model", "Models", "/start",
            "/help", "Help", "/current", "Current session", "/files", "Files",
        }
        if cmd in controls:
            tg._restore_primary_controls()
            return tg.handle_control_message(cfg, msg, cmd)
        if msg.get("photo") or msg.get("document"):
            tg.send_text(cfg, "Send a text name for the session, or Cancel. Attachments are not accepted as names.")
            return True
        title = " ".join(cmd.split())
        if not title:
            tg.send_text(cfg, "Session name cannot be empty. Send a name, or Cancel.")
            return True
        if title.startswith("/"):
            tg.send_text(cfg, "That command is not a session name. Send a name, or Cancel.")
            return True
        if len(title) > tg.SESSION_NAME_MAX_LENGTH:
            tg.send_text(cfg, f"Session name is too long. Use {tg.SESSION_NAME_MAX_LENGTH} characters or fewer.")
            tg._begin_new_session(cfg)
            return True
        try:
            session = tg.create_session(cfg, title)
            if not tg._session_by_id(cfg, session["id"]):
                raise RuntimeError("The new session was created but could not be verified in the session list.")
            tg._set_active_session(session)
        except Exception as e:
            tg.log(f"[{tg.ts()}] session creation failed: {e!r}", flush=True)
            tg.send_text(cfg, "Could not create the session. Check that OpenCode is running and try again.")
            tg._begin_new_session(cfg)
            return True
        tg._restore_primary_controls()
        tg.send_text(cfg, f"<b>Session created and selected:</b> {tg._html_escape(tg.session_title(session))}\n<b>Session ID:</b> <code>{tg._html_escape(session['id'])}</code>", parse_mode="HTML")
        tg._send_keyboard(cfg)
        return True

    # New-session actions work from the main keyboard and any active picker.
    if cmd in (tg.NEW_SESSION, "/newsession", tg.CREATE_SESSION):
        if tg.ACTIVE_PICKER in ("models", "providers", "sessions"):
            tg._restore_primary_controls()
            tg._invalidate_model_message_ref()
        tg._begin_new_session(cfg)
        return True

    if cmd == "Cancel" and tg.ACTIVE_PICKER == "sessions":
        tg._restore_primary_controls()
        tg._send_keyboard(cfg)
        return True
    if cmd == "Open by ID" and tg.ACTIVE_PICKER == "sessions":
        _begin_session_id(cfg)
        return True
    if cmd == "Cancel" and tg.ACTIVE_PICKER in ("providers", "models"):
        tg._restore_primary_controls()
        tg._invalidate_model_message_ref()
        tg._send_keyboard(cfg)
        return True
    if cmd in ("Next", "Previous") and tg.ACTIVE_PICKER == "sessions":
        if tg.SESSION_SNAPSHOT:
            tg._send_session_picker(cfg, tg.SESSION_PAGE + (1 if cmd == "Next" else -1), tg.SESSION_SNAPSHOT)
        return True
    if cmd in ("Previous", "Next") and tg.ACTIVE_PICKER in ("providers", "models"):
        if tg.ACTIVE_PICKER == "models":
            provider_index = tg.MODEL_SELECTION.get("provider")
            if provider_index is not None:
                page = tg.MODEL_SELECTION.get("page", 0) + (1 if cmd == "Next" else -1)
                tg._models_menu(cfg, provider_index=provider_index, page=page,
                             models_snapshot=tg._read_models_cache())
        return True
    if cmd in ("/start", "/help", "Help"):
        if tg.ACTIVE_PICKER is not None:
            tg._invalidate_model_message_ref()
        tg._restore_primary_controls()
        tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)
        tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
        tg.SESSION_SNAPSHOT = []
        tg.SESSION_PAGE = 0
        tg.SESSION_BUTTONS.clear()
        tg.ACTIVE_PICKER = None
        tg._send_keyboard(cfg, configure=(cmd == "/start"))
        tg.send_text(cfg, "<b>Commands</b>\n/session selects a session\n/newsession creates and selects a named session\n/current shows the active target\n/models switches its model\n/files lists received files\n\nSend any text to the active session. Agent replies arrive through <code>tg_send</code> and <code>tg_sendfile</code>.", parse_mode="HTML")
        return True
    if cmd == "Cancel" and tg.ACTIVE_PICKER == "sessions":
        tg._restore_primary_controls()
        tg._send_keyboard(cfg)
        return True
    if cmd in ("/files", "Files"):
        if tg.ACTIVE_PICKER is not None:
            tg._invalidate_model_message_ref()
            tg._restore_primary_controls()
            tg._send_keyboard(cfg)
        sid, _ = tg.resolve_session(cfg)
        directory = tg.FILES / (sid if sid else "unassigned")
        entries = sorted((p for p in directory.iterdir() if p.is_file()),
                         key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
        if not entries:
            tg.send_text(cfg, "No files have been received for the active session.")
        else:
            tg.send_text(cfg, "Files for this session:\n" + "\n".join(str(p) for p in entries[:20]))
        return True
    if cmd in ("/current", "Current session"):
        if tg.ACTIVE_PICKER is not None:
            tg._invalidate_model_message_ref()
            tg._restore_primary_controls()
            tg._send_keyboard(cfg)
        sid, _ = tg.resolve_session(cfg)
        session = tg._session_by_id(cfg, sid) if sid else None
        if session:
            tg.send_text(cfg, f"<b>Active session:</b> {tg._html_escape(tg.session_title(session))}\n<b>Session ID:</b> <code>{tg._html_escape(sid)}</code>", parse_mode="HTML")
        else:
            tg.send_text(cfg, f"Active session: <code>{tg._html_escape(sid or 'not set')}</code>", parse_mode="HTML")
        return True
    if cmd in ("/session", "Sessions"):
        if tg.ACTIVE_PICKER is not None:
            tg._invalidate_model_message_ref()
        tg._restore_primary_controls()
        tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)
        tg.SESSION_PAGE = 0
        tg._send_session_picker(cfg)
        return True
    if cmd in ("/menu", "Menu", "Show menu"):
        tg._restore_primary_controls()
        tg._invalidate_model_message_ref()
        tg._send_keyboard(cfg)
        return True
    if cmd in ("/models", "/model", "Models"):
        if tg.ACTIVE_PICKER is not None:
            tg._invalidate_model_message_ref()
        tg._restore_primary_controls()
        tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
        tg.MODEL_PAGE_STATE.update(provider_index=None, page=0)
        tg.SESSION_BUTTONS.clear()
        tg.SESSION_SNAPSHOT = []
        tg._invalidate_model_message_ref()
        tg.ACTIVE_PICKER = None
        tg._models_menu(cfg)
        return True
    if tg.ACTIVE_PICKER == "sessions" and cmd in tg.SESSION_BUTTONS:
        if msg.get("photo") or msg.get("document"):
            tg.send_text(cfg, "Attachment was not delivered because this message selected a session. Send it again after selection.")
            return True
        selected_sid = tg.SESSION_BUTTONS[cmd]
        session = next((s for s in tg.SESSION_SNAPSHOT if str(s.get("id") or "") == selected_sid), None)
        if not session:
            tg.send_text(cfg, "That session picker has expired. Open /session and choose again.")
            return True
        if not re.fullmatch(r"ses[0-9A-Za-z_-]{6,80}", selected_sid):
            tg.send_text(cfg, "Invalid session ID; the target was not changed.")
            return True
        tg._set_active_session(session)
        tg.SESSION_PAGE = 0
        tg.ACTIVE_PICKER = None
        tg.SESSION_BUTTONS.clear()
        tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
        tg.send_text(cfg, f"<b>Target session:</b> {tg._html_escape(tg.session_title(session))}\n<b>Session ID:</b> <code>{tg._html_escape(selected_sid)}</code>", parse_mode="HTML")
        tg._send_keyboard(cfg)
        return True
    if tg.ACTIVE_PICKER in ("models", "providers", "sessions") and (msg.get("photo") or msg.get("document")):
        tg.send_text(cfg, "Attachment was not delivered because this message was a picker control. Send it again without a picker caption.")
        return True
    stale_session_label = (
        (tg.ACTIVE_PICKER == "sessions" and (
            re.fullmatch(r"\d+\. .+", cmd)
            or re.fullmatch(r".+ \[[0-9A-Za-z_-]{6,80}\]", cmd)
        ))
        or (tg.ACTIVE_PICKER is None and (
            re.fullmatch(r"\d+\. .+", cmd)
            or re.fullmatch(r".+ \[ses[0-9A-Za-z_-]{6,80}\]", cmd)
        ))
    )
    if stale_session_label:
        tg.send_text(cfg, "That session picker has expired. Open /session and choose again.")
        return True
    if cmd == tg.MODEL_BACK and tg.ACTIVE_PICKER == "models":
        tg._models_menu(cfg, models_snapshot=tg._read_models_cache())
        return True
    if tg.ACTIVE_PICKER in ("models", "providers") and cmd in (
            "Sessions", "Current session", "Help", "Files", "/session", "/newsession",
            "/current", "/help", "/files"):
        if cmd in ("Current session", "/current"):
            sid, _ = tg.resolve_session(cfg)
            session = tg._session_by_id(cfg, sid) if sid else None
            if session:
                tg.send_text(cfg, f"<b>Active session:</b> {tg._html_escape(tg.session_title(session))}\n<b>Session ID:</b> <code>{tg._html_escape(sid)}</code>", parse_mode="HTML")
            else:
                tg.send_text(cfg, f"Active session: <code>{tg._html_escape(sid or 'not set')}</code>", parse_mode="HTML")
            return True
        if cmd in ("Help", "/help"):
            tg.send_text(cfg, "<b>Commands</b>\n/session selects a session\n/newsession creates and selects a named session\n/current shows the active target\n/models switches its model\n/files lists received files\n\nSend any text to the active session. Agent replies arrive through <code>tg_send</code> and <code>tg_sendfile</code>.", parse_mode="HTML")
            return True
        if cmd in ("Files", "/files"):
            sid, _ = tg.resolve_session(cfg)
            directory = tg.FILES / (sid if sid else "unassigned")
            entries = sorted((p for p in directory.iterdir() if p.is_file()),
                             key=lambda p: p.stat().st_mtime, reverse=True) if directory.exists() else []
            tg.send_text(cfg, "No files have been received for the active session." if not entries else
                         "Files for this session:\n" + "\n".join(str(p) for p in entries[:20]))
            return True
        if cmd in ("Sessions", "/session"):
            tg.SESSION_PAGE = 0
            tg.SESSION_SNAPSHOT = []
            tg.SESSION_BUTTONS.clear()
            tg._send_session_picker(cfg)
            return True
    if tg.ACTIVE_PICKER == "providers" and cmd in ("Previous", tg.MODEL_BACK, tg.MODEL_CLOSE):
        return True
    selected_provider = tg.MODEL_SELECTION.get("labels", {}).get(cmd)
    if tg.ACTIVE_PICKER == "providers" and tg.MODEL_SELECTION.get("provider") is None and selected_provider is not None:
        tg._models_menu(cfg, provider_index=selected_provider, page=0,
                     models_snapshot=tg._read_models_cache())
        return True
    groups = tg._group_models(tg._read_models_cache())
    providers = tg._ordered_providers(groups)
    if tg.ACTIVE_PICKER == "models" and tg.MODEL_SELECTION.get("provider") is not None:
        provider_index = tg.MODEL_SELECTION["provider"]
        provider = providers[provider_index] if provider_index < len(providers) else None
        items = groups.get(provider, []) if provider else []
        index = tg.MODEL_SELECTION.get("labels", {}).get(cmd)
        if index is not None and 0 <= index < len(items):
            displayed = tg.MODEL_SELECTION.get("models", {}).get(cmd)
            if displayed != (items[index].get("providerID"), items[index].get("id")):
                tg.send_text(cfg, "That model picker is out of date. Open /models and choose again.")
                return True
            try:
                tg._switch_session_model(cfg, items[index])
            except Exception as e:
                tg.log(f"[{tg.ts()}] model switch failed: {e!r}", flush=True)
                tg.send_text(cfg, f"Model switch failed: {tg._html_escape(str(e)[:140])}", parse_mode="HTML")
            else:
                tg.ACTIVE_PICKER = None
                tg.MODEL_SELECTION.update(provider=None, page=0, labels={})
                tg._invalidate_model_message_ref()
                tg._send_keyboard(cfg)
            return True
    return False
