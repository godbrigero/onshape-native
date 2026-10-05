# Install Onshape Native on a device

Onshape Native works with **Claude Code and Codex**. Both use the same local
MCP server, browser extension and modeling skill. Install the extension and
Python companion on the **same computer** that runs your AI client.

This guide covers macOS, desktop Linux and native Windows. The installers select
the appropriate Python executable (`bin/python` or `Scripts/python.exe`). The
release has been exercised on macOS; Windows path handling is covered by tests,
but a full Windows/Linux browser installation has not been live-tested here.
Mobile browsers and cloud-only AI sessions cannot host this local integration.

## 1. Put the source on the device

Extract the clean `onshape-native-0.3.0.zip` into a permanent, writable location,
or copy the source package from this project. Examples:

- macOS/Linux: `~/Tools/onshape-native`
- Windows: `C:\Users\YOUR_NAME\Tools\onshape-native`

The folder should contain `pyproject.toml`, `uv.lock`, `scripts/`, `extension/`,
`skills/`, `data/`, `.codex-plugin/` and `.claude-plugin/`. Keep the folder after
installation: your browser loads the extension from it, and the default private
runtime lives in its `.runtime` directory.

To create a transfer ZIP from an existing checkout, run from `onshape-native`:

```sh
uv run --frozen python scripts/package.py
```

The ZIP goes into `dist/`. It contains source and assets, excluding `.runtime`,
`.venv`, `.mcp.json`, `extension/local-config.js`, `.env` and browser captures.
Do not copy those generated files from another computer; configure this device
to obtain its own paths and pairing token.

## 2. Install the prerequisites

You need:

- A Chromium browser supporting Chrome extension manifest v3, version 120 or
  later, such as Comet, Chrome or Edge, with permission to load an unpacked
  extension. Sign into `https://cad.onshape.com` in that browser profile.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) to install Python
  and the locked dependencies.
- [Claude Code](https://code.claude.com/docs/en/setup) or Codex with its `codex`
  CLI available on `PATH`. Use a current Claude Code release with plugin support.
  The Claude installer was verified with Claude Code 2.1.285.

Install uv using its official platform installer. Close and reopen your terminal
after installing uv or an AI client so the updated `PATH` is available. Check:

```sh
uv --version
```

For your selected client, also run `claude --version` or `codex --version` and
complete that client's normal sign-in. No Onshape API keys are needed.

On Windows, use **native PowerShell** with a Windows browser for this setup.
The extension connects to `127.0.0.1` on its own machine; a server inside WSL,
Docker, SSH or a remote development environment may be in a different network
namespace. Cross-environment forwarding is not configured by this installer.

## 3. Create this device's environment and pairing

Open a terminal **inside the extracted `onshape-native` folder**. For example:

macOS/Linux:

```sh
cd "$HOME/Tools/onshape-native"
```

Windows PowerShell:

```powershell
Set-Location "$HOME\Tools\onshape-native"
```

Then use the same commands on all three platforms:

```sh
uv python install 3.12
uv sync --frozen --python 3.12
uv run --frozen python scripts/configure.py
```

This creates `.venv`, private `.runtime/bridge.json`,
`extension/local-config.js`, and a `.mcp.json` launcher with this device's
absolute paths. Running configuration again reuses the existing token.

To store runtime data elsewhere, use the same explicit path when configuring
and installing either client:

```sh
uv run --frozen python scripts/configure.py --runtime-dir "/absolute/private/runtime"
uv run --frozen python scripts/install_claude.py --runtime-dir "/absolute/private/runtime"
```

For Codex, use `scripts/install_local.py` in the second command. On Windows,
supply a quoted Windows path, for example `"C:\Users\YOUR_NAME\OnshapeRuntime"`.
If using shell HTTP helpers later, set `ONSHAPE_NATIVE_RUNTIME` to that path too.
Do not rotate or print the token as a connectivity troubleshooting step.

## 4. Load the extension

1. In Comet or Chrome, open `chrome://extensions`; in Edge, open
   `edge://extensions`.
2. Enable **Developer mode**, click **Load unpacked**, and select the extracted
   package's **`extension`** folder. Do not select the whole package or a plugin
   cache copy; cache copies deliberately omit the pairing file.
3. Review and enable its site access. The extension uses Onshape access for CAD,
   loopback access for the local bridge, and `webRequest` for export redirects.
4. Open an Onshape document in that profile. Pin the extension if convenient.
   Its popup contains status and one **Connect/Disconnect** button.

The popup can show **Disconnected** until a client starts the MCP server.
Continue with client installation before diagnosing that as an error.

## 5. Install into your AI client

Choose the client you want. Both can share this configured extension/runtime.

| Client | Run inside the source package | Detailed guide |
|---|---|---|
| Claude Code | `uv run --frozen python scripts/install_claude.py` | [Claude Code](claude-code.md) |
| Codex | `uv run --frozen python scripts/install_local.py` | [Codex](codex-plugin.md) |

The installers create a clean local plugin, install its Python dependencies
outside the plugin cache, and register the MCP server plus modeling skill using
the client's CLI. They generate paths for this computer and preserve existing
pairing and unrelated plugins. Installing into Claude Code does not require
Codex, and installing into Codex does not require Claude Code.

Restart the chosen client after installation. For Claude Code, start in your
normal working directory, outside the integration's source folder, so its
generated project `.mcp.json` is not also offered as a second registration.

## 6. Verify the connection

In Claude Code, open `/mcp` and find the plugin's `onshape_native` server. In
Codex, verify `onshape_native` is enabled in the MCP settings. Ask either agent:

> Use Onshape Native. Check `bridge_status`, resolve this Onshape URL, and list
> the document's Part Studios and folders. Do not modify the model.

Paste a real Onshape document/element URL. A working connection reports
`extension_connected: true`. If it reports false, press **Connect** in the
extension popup; its periodic reconnect may take up to about 30 seconds.

For an independent protocol check from the source directory:

```sh
uv run --frozen python scripts/smoke.py --mcp-config .mcp.json
```

This starts the configured MCP process, verifies discovery and URL resolution,
and reports extension connectivity without editing CAD. On a first launch,
the protocol can pass before the extension finishes reconnecting. The smoke
process exits afterward; if it started the bridge, that bridge exits with it.
Your normal AI session starts it again automatically.

## What starts automatically

The client launches `scripts/serve.py` over **stdio**. Its startup starts the
authenticated HTTP/WebSocket companion on `127.0.0.1:8766`, or reuses an existing
companion with the same pairing token. The extension connects to that companion.
No separate server terminal is required for ordinary MCP use.

Port 8766 serves the bridge's REST/native commands; it is **not a Streamable HTTP
MCP endpoint**. Configure a local command/stdio server, not an HTTP MCP URL.
Keep the browser running and signed in. The companion started by an MCP process
ends when that process exits. If two clients reuse it and the owner exits,
restart the remaining client's MCP connection. For independent, simultaneous
client lifetimes, start the shared companion first in a terminal:

```sh
uv run --frozen python scripts/bridge.py
```

Then both clients reuse it until that terminal process stops. Concurrent CAD
edits still require fresh revision checks and coordination.

## Updates, moving devices and removal

- **Update:** update source files while preserving this device's `.runtime` and
  `extension/local-config.js`, run `uv sync --frozen`, then rerun the installer
  for each client. Reload the extension when its code changes and restart the
  AI client. Review any newly requested extension permissions.
- **Move folders:** keep the existing runtime or pass its absolute path with
  `--runtime-dir`; rerun configuration and client installation. Load the
  extension from its new path. Old absolute paths are not automatically repaired.
- **Another device:** transfer the clean ZIP, then repeat this guide. Each device
  gets its own pairing and browser login. No credentials are bundled in the ZIP.
- **Claude removal:** run
  `claude plugin uninstall onshape-native@onshape-native-local --scope user`.
  The source, browser extension and private runtime remain available for Codex.
  Remove the extension from the browser separately when no client needs it.

## Troubleshooting

| Symptom | Check or fix |
|---|---|
| `uv`, `claude` or `codex` not found | Install that prerequisite, reopen the terminal and check its `--version`. |
| Python executable missing | Run `uv sync --frozen`, configure again and rerun the client installer on this device. Do not reuse another device's `.mcp.json`. |
| Extension fails to load `local-config.js` | Run `scripts/configure.py` and load the source `extension` folder, not the secret-free distributed plugin cache. |
| MCP connected, extension disconnected | Open the signed-in browser/profile, enable the extension, click Connect, and ensure both use the same runtime. |
| Port occupied or token mismatch | Identify the existing companion and use its pairing. Close the obsolete bridge and reconnect if needed; do not kill unrelated processes or regenerate tokens blindly. |
| Current window unavailable | Reload the updated extension and keep an Onshape tab active in that browser, or provide the exact document URL. |
| MCP tools absent after install | Restart the client, check plugin enablement and workspace policy, then inspect `/mcp` in Claude Code. |
| Onshape returns permission/plan errors | Use an account/workspace authorized for that action; the bridge does not change Onshape access rights. |

See [agent commands and HTTP formats](agent-guide.md) and
[coverage and limits](coverage.md) after the first connection succeeds.
