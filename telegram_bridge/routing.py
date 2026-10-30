"""Injection queue: admit owner messages into the live OpenCode session."""
import threading
import traceback

import telegram_bridge as tg


def inject_record(cfg: dict, rec: dict) -> bool:
    """Admit one owner message into the live OpenCode session. Returns True on success."""
    text = (rec.get("text") or "").strip()
    if not text and not rec.get("file"):
        tg.log(f"[{tg.ts()}] inject skipped: empty update {rec.get('update_id')}", flush=True)
        return True  # nothing deliverable; treat as done
    body_text = text
    if rec.get("file"):
        body_text = (body_text + "\n" if body_text else "") + f"[attached file: {rec['file']}]"

    delivery = (cfg.get("TG_DELIVERY") or "steer").strip().lower()
    if delivery not in ("steer", "queue"):
        delivery = "steer"
    queued_for = str(rec.get("session_id") or "")
    recorded_agent = str(rec.get("agent") or "").strip().lower()
    current_agent = tg._agent_identity(cfg)
    if recorded_agent == "claude":
        recorded_agent = "claude-code"
    if queued_for and recorded_agent != current_agent:
        # Old inbox entries have no agent marker; fail closed rather than
        # allowing a UUID-shaped session ID to cross agent boundaries.
        tg.log(f"[{tg.ts()}] inject skipped: queued session agent {recorded_agent or 'unknown'} "
               f"does not match configured agent {current_agent}", flush=True)
        tg.send_text(cfg, "Could not deliver this queued message: its original agent does not match the currently configured agent. Select the original agent and resend.")
        return True
    sid, how = tg.resolve_session(cfg)
    if not sid:
        tg.log(f"[{tg.ts()}] inject: no session found (update={rec.get('update_id')})", flush=True)
        return False
    if queued_for and queued_for != sid:
        # A session switch happened while this update waited in the queue.
        # Preserve the original target rather than silently rerouting it.
        if not tg._session_by_id(cfg, queued_for):
            tg.send_text(cfg, "Could not deliver this message to its original session because that session is no longer available. Select a session and resend.")
            return True
        sid = queued_for
        how = "captured-at-receive"
    tg.log(f"[{tg.ts()}] inject target sid={sid} ({how}), delivery={delivery}", flush=True)
    if tg._try_prompt(cfg, sid, body_text, delivery):
        tg.STATE.write_text(sid)
        return True
    if delivery != "queue" and tg._try_prompt(cfg, sid, body_text, "queue"):
        tg.STATE.write_text(sid)
        return True
    return False


def _inject_worker(cfg: dict) -> None:
    mode = (cfg.get("OPENCODE_INJECT") or "1").strip().lower()
    if mode in ("0", "false", "off", "no"):
        tg.log(f"[{tg.ts()}] inject worker inactive (mode={mode!r})", flush=True)
        return
    tg.log(f"[{tg.ts()}] inject worker up: delivery={cfg.get('TG_DELIVERY') or 'steer'}", flush=True)
    while True:
        rec = tg.INJECT_Q.get()
        try:
            try:
                ok = tg.inject_record(cfg, rec)
            except Exception:
                ok = False
                tg.log(f"[{tg.ts()}] inject exception update={rec.get('update_id')}:", flush=True)
                tg.log(traceback.format_exc(), flush=True)
            tries = int(rec.get("_tries", 0))
            if not ok and tries < 12:
                rec["_tries"] = tries + 1
                tg.log(f"[{tg.ts()}] retry {tries + 1}/12 update={rec.get('update_id')} in 25s", flush=True)
                timer = threading.Timer(25, tg.INJECT_Q.put, args=(rec,))
                timer.daemon = True
                timer.start()
            elif not ok:
                tg.log(f"[{tg.ts()}] gave up update={rec.get('update_id')} (kept in inbox.jsonl)", flush=True)
        finally:
            tg.INJECT_Q.task_done()
