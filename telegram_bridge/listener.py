"""Listener daemon: Telegram long-poll loop and auto-start."""
import json
import os
import pathlib
import subprocess
import sys
import threading
import time
import traceback

import telegram_bridge as tg


def start_opencode_listener(cfg):
    """Start the Telegram listener from an OpenCode MCP process if needed."""
    if (cfg.get("TG_AUTOSTART") or "1").strip().lower() in ("0", "false", "off", "no"):
        return
    try:
        tg.BASE.mkdir(parents=True, exist_ok=True)
        if tg.PID.exists():
            pid = int(tg.PID.read_text().strip())
            os.kill(pid, 0)
            cmdline = pathlib.Path(f"/proc/{pid}/cmdline")
            if cmdline.exists() and b"tg_bridge.py\x00listen" in cmdline.read_bytes():
                return
    except (ValueError, OSError):
        pass
    try:
        lock_fd = os.open(tg.BASE / ".listener.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            os.close(lock_fd)
            raise RuntimeError("automatic listener locking requires fcntl on this platform")
        except BlockingIOError:
            os.close(lock_fd)
            return
        # Spawn the entry-point shim, not this package module, so the child's
        # argv matches the /proc cmdline check above.
        import tg_bridge
        subprocess.Popen([sys.executable, str(pathlib.Path(tg_bridge.__file__).resolve()), "listen"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True,
                         env={**os.environ, "TELEGRAM_BRIDGE_HOME": str(tg.BASE)})
    except Exception as e:
        tg.log(f"[{tg.ts()}] listener auto-start failed: {e!r}", flush=True)


def cmd_listen():
    cfg = tg.load_env()
    token = cfg["TG_BOT_TOKEN"]
    owner = str(cfg["TG_CHAT_ID"])
    tg.BASE.mkdir(parents=True, exist_ok=True)
    lock_path = tg.BASE / ".listener.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        import fcntl
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (ImportError, BlockingIOError):
        tg.log(f"[{tg.ts()}] listener already running; exiting", flush=True)
        # Child takes the same lock in cmd_listen; release parent descriptor only
        # after the process has been spawned, avoiding simultaneous start races.
        os.close(lock_fd)
        return 0
    offset = int(tg.OFFSET.read_text().strip()) if tg.OFFSET.exists() else 0
    tg.PID.write_text(str(os.getpid()))
    tg.log(f"[{tg.ts()}] listener up (pid {os.getpid()}), owner={owner}, offset={offset}", flush=True)
    tg._send_keyboard(cfg, configure=True)
    threading.Thread(target=tg._inject_worker, args=(cfg,), daemon=True).start()
    while True:
        try:
            res = tg.api(
                token,
                "getUpdates",
                {"offset": offset, "timeout": 50,
                 "allowed_updates": json.dumps(["message", "callback_query"])},
                timeout=65,
            )
            for u in res.get("result", []):
                offset = u["update_id"] + 1
                cb = u.get("callback_query")
                if cb:
                    cb_chat = str(((cb.get("message") or {}).get("chat") or {}).get("id", ""))
                    cb_sender = str((cb.get("from") or {}).get("id", ""))
                    if cb_chat != owner or cb_sender != owner:
                        tg.log(f"[{tg.ts()}] ignored callback from unauthorized chat {cb_chat}", flush=True)
                        tg.OFFSET.write_text(str(offset))
                        continue
                    try:
                        tg.handle_callback(cfg, cb)
                    except Exception:
                        tg.log(f"[{tg.ts()}] callback error:", flush=True)
                        tg.log(traceback.format_exc(), flush=True)
                    tg.OFFSET.write_text(str(offset))
                    continue
                msg = u.get("message") or {}
                chat_id = str((msg.get("chat") or {}).get("id", ""))
                text = msg.get("text") or msg.get("caption") or ""
                if chat_id != owner:
                    tg.log(f"[{tg.ts()}] ignored update {u['update_id']} from unauthorized chat {chat_id}", flush=True)
                    tg.OFFSET.write_text(str(offset))
                    continue
                sender_id = str((msg.get("from") or {}).get("id", ""))
                if sender_id and sender_id != owner:
                    tg.log(f"[{tg.ts()}] ignored update {u['update_id']} from sender {sender_id}", flush=True)
                    tg.OFFSET.write_text(str(offset))
                    continue
                if tg.handle_control_message(cfg, msg, text):
                    tg.OFFSET.write_text(str(offset))
                    continue
                file_id, file_name = None, ""
                doc = msg.get("document")
                photo = msg.get("photo")
                if doc:
                    file_id = doc.get("file_id")
                    file_name = doc.get("file_name") or f"document_{msg.get('message_id')}"
                elif photo:
                    file_id = photo[-1].get("file_id")
                    file_name = f"photo_{msg.get('message_id')}.jpg"
                active_sid, _ = tg.resolve_session(cfg)
                session_files = tg.FILES / (active_sid if active_sid else "unassigned")
                session_files.mkdir(parents=True, exist_ok=True)
                if file_id:
                    saved = tg._download_file(token, file_id, file_name, destination=session_files)
                else:
                    saved = ""
                rec = {
                    "ts": int(time.time()), "iso": tg.ts(), "update_id": u["update_id"],
                    "chat_id": chat_id, "text": text, "file": saved, "file_name": file_name,
                    "session_id": active_sid,
                }
                with tg.INBOX.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                tg.OFFSET.write_text(str(offset))
                tg.log(f"[{tg.ts()}] stored update {u['update_id']}: {text[:80]} | file={saved}", flush=True)
                tg.INJECT_Q.put(rec)
        except KeyboardInterrupt:
            break
        except Exception as e:  # keep the daemon alive across network hiccups
            tg.log(f"[{tg.ts()}] poll error: {e!r}", flush=True)
            time.sleep(5)
