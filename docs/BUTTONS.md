# Buttons and commands

TeleCode uses ordinary reply keyboards for top-level navigation and session/model
selection. Telegram's client controls whether the user hides or reopens the keyboard.

## Persistent reply keyboard

The keyboard is sent when the listener starts and on `/start` or `/help`. Its markup
sets `one_time_keyboard: true`, requesting that Telegram hide it after a button is
pressed while retaining the client's ability to reopen it. TeleCode never sends
`ReplyKeyboardRemove` for normal navigation. The keyboard has these rows:

```text
[ Sessions ]        [ Current session ]
[ Models ]          [ Help ]
[ /menu ] [ /session ] [ /models ]
```

Labels are English text only. There is no emoji in the keyboard. Each label is
matched exactly after stripping surrounding whitespace. The session-picker body and
formatted status messages use Telegram HTML parse mode; dynamic values escape `&`,
`<`, and `>`. If formatted sending fails, the bridge retries with stripped plain text.
Reply-keyboard and inline-keyboard button labels are plain
text and do not use message parse mode.

| Label | Routes to | Effect |
| --- | --- | --- |
| `Sessions` | `/session` | Sends the paginated session picker. |
| `Current session` | `/current` | Reports the active session title and ID. |
| `Models` | `/models` | Sends the bottom reply-keyboard provider/model picker. |
| `Help` | `/help` | Restores this keyboard and prints command help. |

The help text is fixed: it lists `/session`, `/current`, and `/models`, states that
plain text is routed to the active session, and notes that replies arrive through
`tg_send` and `tg_sendfile`.

## Session picker

`/session` or `Sessions` shows a temporary bottom reply keyboard with session choices.

- Sessions are root, non-archived sessions in the current home directory, ordered by
  the API's descending update order. The bridge requests up to 1,000 and retries
  without a directory filter if the filtered request fails or returns no sessions;
  client-side checks still exclude other directories.
- Page size is 8.
- Each session row is a button labelled with its title and a short session-ID suffix.
  The title is truncated to 36 characters and newlines are removed. The suffix lets
  the bridge recognize stale buttons after a picker is closed.
- The message body lists the eight session names on the current page with their full
  IDs and marks the active target. The reply keyboard is also paginated because
  Telegram limits a keyboard to 100 buttons per message.
- `Previous` and `Next` appear only when a previous or next page exists.
- `Cancel` exits the session picker without changing the target. `/menu` is a
  command shortcut for refreshing controls; the bot does not remove the keyboard.

Selecting a row resolves its exact displayed button label against the picker snapshot,
validates the ID against `ses[0-9A-Za-z_-]{6,80}`, and writes
`active-session.json` atomically with mode
`0600`, resets pagination, and confirms the switch without re-sending the keyboard.
If the label no longer uniquely matches a live session, the bridge asks
you to reopen the list; it does not guess. A stale label ending in a session-ID
suffix is consumed as a control message and never forwarded to the agent.

Only one session is active at a time. Session selection is global to the bridge, not
per chat.

## Current session

`/current` or `Current session` resolves the active target in this order:

1. `active-session.json`, if the ID is valid and still present.
2. `OPENCODE_SESSION_ID` when `OPENCODE_SESSION_MODE=pin`.
3. The most recently updated root session in the home directory.

The reply contains the session label and full ID. If discovery finds nothing, the
reply says the target is unset.

## Model picker

`/models` or `/model` or `Models` sends a bottom reply keyboard. Provider/model pages
update the same menu message when Telegram allows editing; otherwise a replacement
picker is sent. The keyboard uses Telegram's one-time hint and has no custom input placeholder.
The command is handled
before agent routing, so it is never stored as a prompt.

1. The bridge loads the catalogue from `GET /api/model` and writes a local cache on
   success. If the request fails, it reads `models-cache.json`; if that is empty it
   replies that OpenCode is unreachable.
2. Providers are grouped and sorted by model count descending, then by provider ID.
   Each provider button is `providerID (count)`. The message also shows the current
   model when it can be read from the active session.
3. Choosing a provider lists its models, 8 per page, sorted by display name. The
   current model is prefixed with `Current:`.
4. `Previous` and `Next` move within the provider's pages. `Back to providers` returns
   to the provider list. `Close models` dismisses the picker without changing anything.
5. Choosing a model calls `POST /api/session/{sessionID}/model` for the active
   session and confirms with the model name, provider ID, and session ID.

Reply-keyboard selections are accepted only for the active picker and current page;
starting a different picker invalidates the previous picker state. `/menu` closes the
temporary picker, and the main keyboard can open sessions, current-session details,
help, or the model picker from either model-selection page. See
[MODELS.md](MODELS.md) for endpoints, persistence, and failure handling.

## Files

`/files` lists up to 20 regular files in `files/<session-id>/`, newest first. It does
not include subdirectories and does not list files for other sessions. `Files` is accepted as a keyboard selection while a model picker is active, but is not on the main keyboard.

## Routing rules

1. The update's chat ID must equal `TG_CHAT_ID`.
2. The sender ID must equal `TG_CHAT_ID` when Telegram supplies one.
3. Control inputs are matched in this order: help, session picker, model picker,
   files, current session, cancel, next page, previous page, session label, stale
   session label.
4. Anything else is stored in `inbox.jsonl` and queued for the active session.
5. Documents and photos are downloaded before storage and placed under
   `files/<session-at-receive>/`. The record carries that session ID, so a later
   switch does not reroute a queued item. If the original session no longer exists
   when the queue reaches it, the bridge reports the loss and leaves the item in the
   inbox rather than sending it elsewhere.

A slash command with a bot mention suffix, such as `/current@my_bot`, is normalized
by removing the suffix before matching. Unrecognized slash commands are not special
cased; they are routed to the agent as text.
