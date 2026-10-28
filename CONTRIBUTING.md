# Contributing

Contributions are welcome for documentation, tests, adapters with a verifiable
session API, and hardening of the existing OpenCode path. Open an issue before a
large change so the scope can be agreed first.

## Development setup

Requirements: Python 3.11 or newer, `bash`, and `make` for the convenience targets.
There is no virtual environment requirement and no third-party package.

```sh
git clone https://github.com/aetherdz/telecode.git
cd telecode
python3 --version
make check
make test
```

`make check` runs `py_compile` on `tg_bridge.py` and `tg_mcp.py`. `make test` runs
`python3 -m unittest discover -s tests -v`. Neither target performs network access.

For a manual run, point the processes at a temporary runtime directory so real
credentials and state are untouched:

```sh
export TELEGRAM_BRIDGE_HOME="$PWD/.dev-runtime"
mkdir -p "$TELEGRAM_BRIDGE_HOME"
chmod 700 "$TELEGRAM_BRIDGE_HOME"
cp .env.example "$TELEGRAM_BRIDGE_HOME/telegram.env"
chmod 600 "$TELEGRAM_BRIDGE_HOME/telegram.env"
```

Add a test bot token and your numeric chat ID, then run:

```sh
python3 tg_bridge.py status
```

Never use a production bot for development or tests.

## Code style

- Python standard library only. Do not add runtime dependencies. `tomllib` is
  available because the minimum version is 3.11.
- No `shell=True`. Pass argument lists to `subprocess.run` and `subprocess.Popen`.
- Keep `stdout` clean in `tg_mcp.py`; it carries JSON-RPC frames. Log to `stderr`.
- Validate session IDs with `ses[0-9A-Za-z_-]{6,80}` and quote them in URL paths.
- Treat inbound Telegram text, captions, and filenames as untrusted.
- Write state atomically: temporary file in the same directory, correct mode,
  `fsync`, `os.replace`.
- Preserve existing file modes in installer writes. Never overwrite a config
  silently; keep the backup and confirmation flow.
- Keep shell scripts compatible with `bash` and safe under `set -euo pipefail`.
- Do not add emoji to user-facing output, the keyboard, documentation, or the site.
- Keep prose lines near 90 characters and use sentence-case headings.
- Prefer explicit error messages over silent failures. Redact tokens and chat IDs.

## Tests

Use `unittest`, matching the existing suites:

- `tests/test_bridge.py` covers session labels, atomic active-session state, the file
  allowlist, the fail-closed Claude adapter, and stale session-button handling.
- `tests/test_setup_cli.py` covers wordmark width, Codex TOML preservation and
  duplicate refusal, JSON schema refusals, and mode-preserving atomic writes.

Tests must not call Telegram, OpenCode, or any network service. Use `unittest.mock`
and temporary directories. Add a regression test for every bug fix. When changing
routing, cover both the authorized path and the rejection path. When changing the
allowlist, test both inside-root and outside-root paths.

Run the full suite before opening a pull request:

```sh
make check
make test
```

## Commit style

Use an imperative subject line, at most 72 characters, optionally prefixed with a
scope:

```text
listener: preserve captured session for queued attachments
installer: refuse invalid Codex TOML without writing
docs: correct model switch endpoint
```

Keep the body focused on why the change is needed and any migration or security
impact. One logical change per commit. Do not mix formatting-only edits with behavior
changes. Do not include generated caches, runtime state, or secrets.

## Pull request checklist

- [ ] `make check` passes.
- [ ] `make test` passes and new behavior has tests.
- [ ] No new dependency, `shell=True`, or network call in unit tests.
- [ ] Session IDs are validated and URL-quoted.
- [ ] File operations use atomic writes, `0600` where appropriate, and mode
      preservation.
- [ ] No emoji added to code, docs, or user-facing strings.
- [ ] No token, chat ID, session ID, or runtime file is committed.
- [ ] Documentation is updated for behavior, configuration, or security changes.
- [ ] Claims about CLI support match the adapters; do not describe MCP-only clients
      as having targeted session routing.
- [ ] The change does not modify `index.html` or assets unless the pull request is
      specifically about the project site.
