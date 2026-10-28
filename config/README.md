# Host config destinations

These example files show the MCP server stanza. The interactive installer
detects local CLIs and known config locations, writes backups, and asks before
modifying a supported JSON/TOML config. Paths in examples use `/home/USER` and
must be adapted to the current platform.

Codex CLI is configured in `~/.codex/config.toml`; the installer appends a
`[mcp_servers.telegram-bridge]` stanza while preserving existing settings.
OpenCode uses its `mcp.servers` map. Claude Code, Cursor, Gemini CLI, Cline, and
Roo Code consume MCP server configuration but do not automatically provide the
same session-targeted injection API.
