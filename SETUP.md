# ⚡ Universal Memory — Automated Agent Setup Guide

This guide is designed for AI coding agents (Claude Code, Antigravity, Codex) to set up Universal Memory automatically with zero friction.

## Automated Execution Protocol for AI Agents:

1. **Verify Python 3.10+**:
   - Run `python --version` or `python3 --version`.
   - Universal Memory requires zero external pip packages (it runs entirely on Python's standard library: `sqlite3`, `json`, `os`, `hashlib`, `re`, `datetime`).

2. **Obsidian Vault Directory**:
   - Check default locations: `~/Desktop/GitHub/obsidian` or `~/obsidian`.
   - If no vault exists yet, create `~/obsidian` to serve as the local Markdown archive.
   - Optional: set `UNIVERSAL_MEMORY_VAULT` environment variable pointing to the vault root.

3. **Verify Integrity & Tests**:
   - Execute:
     ```bash
     python -m unittest discover tests
     ```
   - Ensure all 101 tests pass with zero failures.

4. **Register in AI Agent MCP Config**:
   Add to `mcp_config.json` (Antigravity), `claude_desktop_config.json` (Claude Code), or Cursor MCP settings:
   ```json
   {
     "mcpServers": {
       "universal-memory": {
         "command": "python",
         "args": ["-X", "utf8", "<absolute-path-to-universal-memory>/server.py"],
         "env": {
           "UNIVERSAL_MEMORY_VAULT": "<absolute-path-to-obsidian>"
         }
       }
     }
   }
   ```

5. **Initial Sync**:
   Run the MCP server or execute:
   ```bash
   python -c "import memory_index; print('Indexed files:', memory_index.sync_index())"
   ```
   Universal Memory will initialize the SQLite FTS5 database and knowledge graph automatically.
