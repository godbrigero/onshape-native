# Installation and updates

## Requirements

- A local AI client: Codex with the `codex` CLI, Claude Code with the `claude` CLI, or any client supporting stdio MCP.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) on PATH. It installs Python 3.12 and the locked dependencies automatically.
- A Chromium browser supporting unpacked Manifest V3 extensions, signed into `cad.onshape.com` on the same machine.

Client installation, account sign-in and browser extension approval are prerequisites/manual steps. The installer does not install AI clients or bypass browser approval. Use native Windows PowerShell with a Windows browser; WSL, containers, SSH and cloud-only clients are not automatically connected to the host browser.

## One setup command

```sh
uv run --python 3.12 https://raw.githubusercontent.com/godbrigero/onshape-native/main/install.py --client codex
```

Choose `--client claude`, `--client both`, or `--client generic` as appropriate. Run the command from any directory. For an already downloaded checkout or release ZIP, use:

```sh
uv run --python 3.12 install.py --client codex
```

Useful options:

| Option | Purpose |
|---|---|
| `--directory "PATH"` | Choose the downloaded source/extension location. Must be new or installer-managed. |
| `--runtime-dir "PATH"` | Choose the private pairing/artifact location. Keep it outside downloaded source. |
| `--source "PATH"` | Install from an existing checkout. |
| `--ref TAG_OR_COMMIT` | Select a GitHub source revision instead of `main`. |

For reproducible remote installation, pin the raw script URL and `--ref` to the same commit. Review the script before executing if required by your environment.

Default application data locations are `~/Library/Application Support/OnshapeNative` on macOS, `$XDG_DATA_HOME/onshape-native` (or `~/.local/share/onshape-native`) on Linux, and `%LOCALAPPDATA%\OnshapeNative` on Windows. These are computed on the destination device. Paths in generated `.mcp.json` are intentionally absolute and private; they are not portable files to commit or share.

## Browser and client

1. Open the browser's extensions page (for example `chrome://extensions` or `edge://extensions`).
2. Enable Developer mode and load the **extension directory printed by the installer**.
3. Sign into Onshape in that browser profile.
4. Restart your AI client and check that `onshape_native` is available. In Claude Code, use `/mcp`.

The server starts its loopback HTTP companion automatically when the MCP client launches it. Pairing uses a device-generated secret; Onshape cookies stay in the browser. Do not run multiple separately paired bridges on port 8766.

For `generic`, merge the generated `.mcp.json` server entry into your client's stdio MCP configuration without replacing unrelated servers. Client configuration layouts vary, so this step is manual. The printed skill path contains optional agent instructions.

## Updates

Repeat the remote command with the same destination, or update your checkout and rerun its `install.py`. Installer-managed source is replaced; keep code edits in a separate checkout. Existing pairing is reused. Restart the AI client afterward. Reload the browser extension only when its files change. If you selected a custom runtime, keep using it; managed remote installs remember it.

Do not share `.mcp.json`, `.runtime`, virtual environments, `extension/local-config.js`, or installer marker files. To distribute a clean source ZIP, run `uv run python scripts/package.py`. A recipient configures fresh pairing on their own computer.

## Troubleshooting

- **Missing client CLI:** put `codex` or `claude` on PATH, or choose `generic`.
- **Extension disconnected:** check the loaded extension, signed-in Onshape tab, and loopback port 8766. Browser and server must share the same host.
- **Old tool behavior:** rerun the installer and restart the client; plugin installations contain separate source copies.
- **New extension location:** remove the old unpacked extension and load the printed directory.

The installer selects Windows/Linux/macOS paths automatically. Path handling is tested; full installation and browser integration on Windows and Linux still require live validation.
