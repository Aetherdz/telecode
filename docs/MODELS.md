# Model switching

`/models` changes the model of the active OpenCode session. Model providers and models
appear in Telegram's bottom reply keyboard, matching the session picker style. Menu
text uses HTML parse mode; dynamic values escape ampersands and angle brackets. The bridge
does not keep a model setting of its own: it asks the local OpenCode server to update
the session, and the server applies the model to subsequent turns.

## Flow

1. `/models`, `/model`, or the `Models` button is intercepted by the listener before
   prompt injection.
2. The bridge runs `opencode api get /api/model` and parses the catalogue.
3. On success it writes `models-cache.json` in the runtime directory. On failure it
   falls back to that cache.
4. The bridge groups models by `providerID`, sorts providers by model count
   descending and then by provider ID, and displays them in a reply keyboard. This first screen
   skips the active-session lookup so the provider list appears without waiting on a
   second API request.
5. Selecting a provider replaces the bottom keyboard with its models, 8 per page,
   sorted by display name. Previous/next and back-to-providers buttons navigate pages.
6. Selecting a model switches the active session model.
7. The switch resolves the active session, then runs:
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

When a provider's model page is rendered, the bridge calls
`GET /api/session/{sessionID}` for the active session. If the response contains
`model.id`, that value is shown in the header and the matching model row is prefixed
with `Current:`. A lookup failure is silent: the picker still works, but no current model is
marked. The bridge does not read the model from local state.

## Pagination and selection

- Model pages contain 8 entries.
- Page numbers are clamped to the valid range.
- `Previous` and `Next` are rendered only when the corresponding page exists.
- `Back to providers` returns to the provider list; `Close models` restores the
  ordinary Telegram control keyboard.
- Reply-keyboard text labels are mapped to the active provider page. A new picker
  invalidates the prior selection state.
- Selection uses model labels from the current cached provider page. Duplicate display
  names are disambiguated with a short row suffix.

## Failure modes

| Condition | Behavior |
| --- | --- |
| OpenCode service down | Catalogue request fails; cached models are used if present. |
| Service down and no cache | Reply that models could not be fetched; no keyboard is sent. |
| Catalogue request slow | 45-second timeout, then the same cache fallback. |
| Cache file corrupt or missing fields | Invalid entries are ignored; an empty result is treated as no cache. |
| Cache changed between render and selection | The bridge rejects stale/out-of-range selections instead of switching an unrelated row. |
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
