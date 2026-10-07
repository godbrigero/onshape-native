# Onshape Native for Claude Code

This plugin supplies the **same 35 MCP tools and modeling skill** as the Codex
integration. Claude Code launches the stdio MCP server; the server automatically
starts or reuses the local HTTP bridge connected to the Onshape extension.
No Codex installation or Onshape API keys are required.

## Install on this device

First follow [device setup](installation.md) to install uv/Python and Claude Code,
extract this package, configure pairing and load the browser extension. From the
`onshape-native` source directory, the short command sequence is:

```sh
uv sync --frozen
uv run --frozen python scripts/configure.py
uv run --frozen python scripts/install_claude.py
```

These commands work in macOS/Linux terminals and Windows PowerShell. For a
custom private runtime, pass the same `--runtime-dir` to both Python scripts.
No path or username in the repository needs editing.

The installer:

1. Verifies that the runtime and extension use the same existing pairing.
2. Copies a clean plugin into `~/.claude/onshape-native-local/plugin` (under
   `CLAUDE_CONFIG_DIR` when set), including its own code, catalogs and skill.
3. Creates a Python environment at `RUNTIME/claude-venv` and generates a local
   `.mcp.json` with absolute executable, launcher and runtime paths.
4. Validates the plugin using the Claude CLI, then adds its dedicated local
   marketplace and installs `onshape-native@onshape-native-local` in user scope.

The marketplace and installed cache omit tokens, browser captures and virtual
environments. The loaded browser extension remains in the source directory.
Other plugins and the Codex registration remain untouched. The installer can be
rerun to update this plugin; it refuses to replace an unmanaged installation or
an unrelated marketplace using the same name. It respects an explicitly
disabled existing plugin rather than re-enabling it automatically.

Restart Claude Code from your normal working directory after installation.
Avoid starting inside the integration's source folder: its generated `.mcp.json`
can otherwise be offered as an additional project-scoped server.

## Confirm it works

Check registration in a terminal:

```sh
claude plugin list --json
```

In an interactive Claude Code session, use `/mcp` to inspect the plugin's native
server. Plugin tools may have a plugin/server prefix; the server key is
`onshape_native`. Then enter:

```text
/onshape-native:onshape-native-modeling Inspect this Onshape URL and report its
Part Studios, folders and feature errors. Do not change the model: YOUR_URL
```

Or use natural language:

> Use Onshape Native to make the cube at this URL 50 mm tall. Preserve the other
> features and verify the final dimensions.

The skill resolves the task target, inspects state, discovers schemas, performs
authorized edits and verifies results. It prefers backend commands, with UI
fallback only when needed. “Use my current Onshape tab” works when the updated
extension supplies window metadata; otherwise give an explicit link.

## MCP-only registration alternative

If you prefer a manually configured MCP server without installing the skill
plugin, use the generated `.mcp.json` values with Claude's local stdio setup.
Choose **either** this registration or the plugin above to avoid duplicate tools.

Example for macOS/Linux, replacing each path with this device's real source path:

```sh
claude mcp add --scope user --transport stdio \
  --env "ONSHAPE_NATIVE_RUNTIME=/absolute/path/onshape-native/.runtime" \
  onshape_native -- "/absolute/path/onshape-native/.venv/bin/python" \
  "/absolute/path/onshape-native/scripts/serve.py"
```

Windows PowerShell example:

```powershell
claude mcp add --scope user --transport stdio `
  --env "ONSHAPE_NATIVE_RUNTIME=C:\Tools\onshape-native\.runtime" `
  onshape_native -- "C:\Tools\onshape-native\.venv\Scripts\python.exe" `
  "C:\Tools\onshape-native\scripts\serve.py"
```

Use the generated environment value if you configured a custom runtime. Check
`claude mcp get onshape_native` and `/mcp`. This alternative loads MCP server
instructions and tools, but does not install the `/onshape-native:...` skill.
Read the [agent guide](agent-guide.md) for the modeling workflow.

## Update and remove

Update the source, sync dependencies and rerun `scripts/install_claude.py`.
Restart Claude Code to use the refreshed plugin. The installer updates only
`onshape-native-local`; it does not refresh unrelated marketplaces.

To remove the plugin registration:

```sh
claude plugin uninstall onshape-native@onshape-native-local --scope user
```

For the MCP-only alternative, use `claude mcp remove --scope user onshape_native`.
Neither operation deletes the source extension or its private pairing/runtime.

The integration uses Claude's documented
[plugin MCP startup](https://code.claude.com/docs/en/mcp#plugin-provided-mcp-servers),
[local marketplace](https://code.claude.com/docs/en/plugin-marketplaces) and
[skill](https://code.claude.com/docs/en/skills) mechanisms. Full device setup,
runtime lifecycle and troubleshooting are in [installation.md](installation.md).
