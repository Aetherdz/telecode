# Model switching

`/models` changes the model of the active OpenCode session. The menu uses Telegram's
`MarkdownV2` parse mode for message text; dynamic names are escaped before formatting.
Inline keyboard button labels are plain text and are not parsed as Markdown. The
bridge does not keep a model setting of its own: it asks the local OpenCode server to update the session,
and the server applies the model to subsequent turns.

## Flow

1. `/models`, `/model`, or the `Models` button is intercepted by the listener before
   prompt injection.
2. The bridge runs `opencode api get /api/model` and parses the catalogue.
3. On success it writes `models-cache.json` in the runtime directory. On failure it
   falls back to that cache.
4. The bridge groups models by `providerID`, sorts providers by model count
   descending and then by provider ID, and sends an inline keyboard.
5. Selecting a provider shows its models, 8 per page, sorted by display name.
6. Selecting a model resolves the active session, then runs:
   `opencode api post /api/session/{sessionID}/model` with the JSON body below.

```json
{
  "model": {
    "id": "model-id",
    "providerID": "provider-id"
  }
}
```

The session ID is validated against `ses[0-9A-Za-z_-]{6,80}` and URL-quoted with an
empty safe set before it is placed in the path.

The command exits non-zero on an API error or an unreachable service. The bridge
then replies with `Model switch failed:` followed by up to 140 characters of the
error text. A successful switch is confirmed with the model name, provider ID, and
session ID.

## Catalogue source

`GET /api/model` is the only catalogue source. Each entry is normalized to:

| Field | Source | Required |
| --- | --- | --- |
| `id` | `modelID`, falling back to `id` | Yes |
| `providerID` | `providerID` | Yes |
| `name` | `name`, falling back to the model ID | No |

Entries missing a model ID or provider ID are dropped. Duplicate IDs are not merged;
the picker treats each entry as a separate row.

The API is reached through the `opencode` binary resolved from `OPENCODE_BIN`, then
`~/.opencode/bin/opencode`, then `PATH`. A 45-second timeout applies to the catalogue
request, 30 seconds to the switch, and 20 seconds to the current-model lookup.

## Current model display

When the provider list or a model page is rendered, the bridge calls
`GET /api/session/{sessionID}` for the active session. If the response contains
`model.id`, that value is shown in the header and the matching model row is prefixed
with `Current:`. A lookup failure is silent: the picker still works, but no current model is
marked. The bridge does not read the model from local state.

## Pagination and callbacks

- Model pages contain 8 entries.
- Page numbers are clamped to the valid range.
- `Previous` and `Next` are rendered only when the corresponding page exists.
- `Providers` re-renders the provider list; `Close` dismisses the menu.
- Callback payloads are indices (`mdl:p:<provider>`, `mdl:l:<provider>:<page>`,
  `mdl:s:<provider>:<index>`), not model IDs.
- A model selection reads `models-cache.json` and maps indices back to entries. If
  the provider index or model index is out of range, the bridge reports an expired
  menu and asks you to send `/models` again.
- Because selection reads the cache rather than the menu's in-memory list, a
  concurrent `/models` that refreshes the cache between rendering and tapping can
  change which model an index resolves to. Reopen the picker if the catalogue may
  have changed.

## Failure modes

| Condition | Behavior |
| --- | --- |
| OpenCode service down | Catalogue request fails; cached models are used if present. |
| Service down and no cache | Reply that models could not be fetched; no keyboard is sent. |
| Catalogue request slow | 45-second timeout, then the same cache fallback. |
| Cache file corrupt or missing fields | Invalid entries are ignored; an empty result is treated as no cache. |
| Cache stale between render and selection | Index lookup may fail; the bridge reports an expired menu. |
| No active session | Switch is refused with a message; nothing is posted. |
| Session disappeared | `resolve_session` drops the stale selection and falls back to discovery or pin. |
| Session busy | The bridge posts the switch regardless; the server decides whether to accept it. A server error is reported. |
| API returns non-JSON or non-zero exit | The switch fails and the error is truncated into the reply. |

No retry is attempted for model requests. Retries apply only to prompt injection.

## Privacy

The bridge sends only the model switch request to the local OpenCode API. It does not
send prompts, message text, file contents, or attachment paths to any model provider
as part of `/models`. The catalogue and the picker contain provider IDs, model IDs,
and display names. `models-cache.json` stores the same names plus a timestamp and is
written with mode `0600`.

The bridge itself makes no outbound request to a model provider. Any provider traffic
is generated by the coding-agent session when it processes a prompt.
