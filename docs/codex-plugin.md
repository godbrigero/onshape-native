# Install Onshape Native in Codex

This package is a standalone personal Codex plugin containing the
`onshape_native` MCP server and the `onshape-native-modeling` skill. The official
API plugin can remain installed beside it. No API keys are required.

## Install or update locally

Prerequisites: Codex CLI available as `codex`, `uv`, and the browser extension
configured and enabled as described in the [README](../README.md).

From the source `onshape-native` directory:

```sh
uv sync --frozen
.venv/bin/python scripts/configure.py
.venv/bin/python scripts/install_local.py
```

If already paired, keep the existing runtime; configuration reuses its token.
For a custom runtime set `ONSHAPE_NATIVE_RUNTIME` consistently for both commands.
The installer also accepts `--runtime-dir /absolute/path/to/runtime`.

The installer copies a clean package into `~/plugins/onshape-native`, merges its
entry into `~/.agents/plugins/marketplace.json`, and runs
`codex plugin add onshape-native@personal --json`. It preserves other plugins and
backs up the marketplace file. It refuses to overwrite an unmanaged destination.
Rerun from the source checkout to update; keep the source and runtime available.

The installed package contains its own Python code, catalogs, docs, extension
source and skill. Its generated `.mcp.json` launches the installed server using a
dedicated environment at `RUNTIME/plugin-venv`; secrets and artifacts stay in
`RUNTIME`. It does not import `onshape-api` or depend on another plugin's scripts.
Codex's cached plugin copy has no pairing token, `.venv`, `.env`, or browser
captures. No server process is started by installation itself.

Continue loading the configured extension from the original source directory's
`extension` folder. The distributed copy deliberately omits `local-config.js`.
The existing pairing works with the installed server. After Python changes,
restart an existing companion; after extension changes, reload the extension in
Comet, reviewing any newly requested permission before granting it. Reload is
separate from installing the Codex plugin.

Start a **new Codex task** after installation so its skill catalog and MCP tools
are loaded. Check registration with:

```sh
codex plugin list --marketplace personal --json
```

## Give the agent a task

Either use natural language or explicitly invoke `$onshape-native-modeling`:

```text
Use Onshape Native to inspect this model: https://cad.onshape.com/documents/...

Use Onshape Native on my current Onshape tab. Make the selected Part Studio's
extrusion 30 mm deep, preserve the other features, and verify the dimensions.

Use $onshape-native-modeling with this link. Duplicate this Part Studio as
"Variant", then move the original into a new document folder called "Original".
```

The skill resolves the link/current tab, inspects the model and hierarchy,
searches for the appropriate commands, makes the requested edits, then verifies
the result. A supplied link is authoritative; “current” uses the active Onshape
tab in the connected browser's last-focused normal window. With multiple
candidate targets or an old extension lacking window metadata, the agent asks
for a link or explicit tab selection. It never guesses from the first open tab.

`resolve_target(url=...)` works without the browser because parsing is local.
Reading or editing CAD still requires the connected, signed-in browser. Native
editor operations may load a background tab. This is headless command execution
with a browser session, not a browser-free Onshape service.

## First read-only check

Call these tools through the `onshape_native` MCP server:

```text
bridge_status {}
resolve_target {"url":"YOUR_ONSHAPE_URL"}
resolve_target {}
search_commands {"task":"inspect Part Studios, assemblies and document folders"}
document_tree {"url":"RESOLVED_URL"}
```

Only use `resolve_target {}` when testing the current browser context. Keep the
resolved URL for the rest of the task. For a Part Studio, follow with
`inspect_model`; for an assembly, `element_tree`.

The [agent guide](agent-guide.md) contains exact arguments and HTTP equivalents.
The [skill](../skills/onshape-native-modeling/SKILL.md) is the actual instruction
file Codex discovers. Plugin layout follows the supported
[Codex plugin format](https://developers.openai.com/plugins/build/plugins).
