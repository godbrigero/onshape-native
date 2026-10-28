# Onshape Native — a reverse-engineered Onshape API with a browser extension

An MCP server for AI-assisted CAD in Onshape. It exposes Onshape's native editor commands and browser-authenticated REST calls through a local API, using a small extension connected to your signed-in browser. No Onshape API keys required.

Use it with **Codex, Claude Code, or another client supporting local stdio MCP servers**. Give your agent an Onshape URL or ask it to use the current Onshape tab.

## Install

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and your AI client first. Then run this command in Terminal or PowerShell:

```sh
uv run --python 3.12 https://raw.githubusercontent.com/godbrigero/onshape-native/main/install.py --client codex
```

Replace `codex` with `claude`, `both`, or `generic`. Add `--directory "PATH"` to choose where the source and extension live. For a local checkout, run `uv run --python 3.12 install.py --client codex` instead.

The installer downloads the server, creates its Python environment, generates private pairing data on your device, and registers the selected client. `generic` generates a `.mcp.json` entry to import into your client's MCP settings.

**Finish in your browser:** open its extensions page, enable Developer mode, choose **Load unpacked**, and select the extension folder printed by the installer. Sign in to Onshape, then restart your AI client. Browser approval cannot be automated by this installer.

The AI client, server and Chromium browser must run on the same computer. The installer handles macOS, Linux and Windows paths; full browser setup has been tested on macOS only. See [installation and updates](docs/installation.md).

## What it does

- Discover commands, inspect geometry, and edit sketches, features and assemblies.
- Traverse and edit tabs, folders and feature trees; inspect mass and materials.
- Control visibility, camera views and mate motion; capture the viewport.
- Open managed shadow/minimal editors, refresh stale tabs, and close task editors after verification. See [editor tabs](docs/editor-tabs.md).
- Return compact summaries, with complete saved details available through one tool: `artifact_page`.

It prefers backend commands and provides UI fallbacks where needed. This is an **unofficial, reverse-engineered integration**: complete Onshape API/UI parity is not guaranteed, and native commands can change with Onshape releases.

## Development

```sh
uv sync --frozen
uv run pytest
uv run python scripts/package.py
```

Generated launchers, pairing tokens, caches and environments stay local and are excluded from source control and release ZIPs. [Response formats](docs/response-compression.md) · [Measured token savings](docs/token-audit/compression/README.md) · [Modeling skill](skills/onshape-native-modeling/SKILL.md)


Native assembly movement, mate/group parameter edits, and geometry measurement
are available through `assembly_transform`, `assembly_feature`, and
`native_measure`. Camera changes no longer require a model revision, and native
modeling supports element-scoped revision guards. See
[the native modeling workflow](docs/display-controls.md#native-modeling-and-measurement)
and [live regression results](docs/native-modeling-regression.md).
After updating an existing installation, reload the browser extension and start
a new AI-client session so the new MCP tool schemas are loaded.


### Editing FeatureScript without copy/paste

Use `feature_studio(action="read", url=FEATURE_STUDIO_URL)` to get the current
source, a snapshot, and an editable local `.fs` file. Then either:

- Send `action="edit"`, the snapshot, and `patches: [{"old":"exact existing text", "new":"replacement"}]`.
- Edit the local file and send `action="edit"`, the snapshot, and its `source_path`.

Set `preview=true` on an edit to review its diff without saving. Each patch must
match exactly once. The tool compares current source before writing, uses the
current document revision to reject concurrent races, reads the saved source
back, and retrieves exported feature specifications. It never silently overwrites
another source edit or retries an uncertain write. The original source remains
in the snapshot; a later explicit edit can restore it against a fresh snapshot.
Local files are uploaded only when requested, with no background watcher.

The API does not expose complete compiler diagnostics through this endpoint;
`check` reports the available feature specifications, not a guarantee that all
code compiles or dependent geometry regenerated. This convenience tool uses
browser-session REST and requires no API keys.
