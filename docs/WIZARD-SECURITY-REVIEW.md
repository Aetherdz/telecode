# Setup wizard security review (detection scope)

## Verified

- `telegram_bridge/detection.py` derives client availability from `setup_cli.HOSTS`
  and `setup_cli.discover`; this proves executable/config presence only, not a
  working client, MCP registration, or session-routing capability.
- The support distinctions below follow `README.md`'s CLI table, `docs/CLI.md`'s
  support matrix, and `adapters/README.md`: OpenCode/Claude routing is documented
  as supported; Codex/Cursor routing is experimental; the remaining listed
  clients are outbound-only. "Other MCP client" is manual, not detected.
- Session summaries read OpenCode session metadata JSON only, cap each read at
  64 KiB and output at three rows, omit transcript/message fields, and reject
  symlinked/out-of-home files. Directory browsing is immediate-child only and
  rejects symlink escapes.
- `setup_cli.discover` uses executable lookup and readable config-file existence;
  it does not validate config contents. Therefore the wizard must not describe
  these presence signals as a validated installation or functional integration.

## Hypotheses / unverified

- Other CLIs may keep useful session metadata in additional locations, but this
  implementation intentionally does not infer or read those formats.
- The local filesystem can change between path checks and reads (TOCTOU). Current
  containment checks and bounded reads reduce exposure but do not provide a
  race-free descriptor-relative traversal guarantee.
- Credential-like text in metadata is masked heuristically; no generic pattern
  can guarantee detection of every secret format. Metadata remains untrusted.

No claim is made here that experimental adapters have been independently
validated. See the referenced support documents for their stated limits.
