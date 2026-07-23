# Claude Code reference plugin

A minimal, working plugin that exercises every component surface
Claude Code exposes to plugins: MCP server, lifecycle hook, slash
command, skill, and subagent. Also demonstrates a practical
correlation pattern for stitching together the two things Claude Code
does not natively connect — HTTP MCP requests and the Claude Code
session that made them.

Layout:

```
.
├── mcp-server.py          # standalone HTTP MCP server + dashboard
└── my-plugin/
    ├── .claude-plugin/
    │   └── plugin.json    # plugin manifest
    ├── .mcp.json          # MCP server config (points at mcp-server.py)
    ├── hooks/
    │   ├── hooks.json     # SessionStart hook registration
    │   └── session-start.sh
    ├── commands/
    │   └── plugincmd.md   # slash command
    ├── skills/
    │   └── probe-skill/
    │       └── SKILL.md
    └── agents/
        └── probe-agent.md
```

## Running it

Start the server in one terminal:

```
LOG_FILE=/tmp/refplugin-log PORT=18796 python3 mcp-server.py
```

Then in another terminal launch Claude Code with the plugin loaded:

```
claude --plugin-dir ./my-plugin
```

Open http://127.0.0.1:18796/ for the dashboard. Every tool call
routed through this plugin's MCP is recorded and joined to the
Claude Code session that made it.

## Exercising each surface

- **Slash command:** type `/reference-plugin:plugincmd anything` in
  Claude Code. Plugin commands are namespaced `<plugin>:<command>`.
- **Skill:** type `/probe-skill`. Skills are invoked by their bare
  name (no namespace).
- **Subagent:** ask Claude Code to use the `probe-agent` subagent via
  the Agent tool — subagents are not slash-invokable.
- **MCP tool:** ask Claude Code to call `call-tool` with a payload.
- **Hook:** fires automatically on every SessionStart (including
  after `/clear`, `/compact`, `/resume`).

## The correlation pattern

The Claude Code session id is *not* transmitted in HTTP MCP requests
— neither in headers, URL, request body, nor `_meta`. To attribute
tool calls to sessions we bridge two out-of-band channels:

1. `headersHelper` in `.mcp.json` runs a shell command at MCP init
   time. Its stdout is parsed as JSON and used as HTTP headers on
   every subsequent request to the MCP endpoint. We mint a random
   `mcp_startup_id`, write it to `/tmp/refplugin-startup-$PPID`, and
   emit it as `x-mcp-startup-id`.
2. `session-start.sh` runs later as a SessionStart hook. It shares
   the same PPID as `headersHelper` (both are direct children of the
   claude process), reads the rendezvous file, receives the
   Claude Code `session_id` on stdin, and POSTs the tuple to
   `/register-session`.
3. The server persists both sides and joins on `mcp_startup_id` when
   rendering the dashboard.

### What lives where in the timeline

```
+0ms    MCP initialize      ← headersHelper runs here (once)
+~200ms SessionStart hook   ← rendezvous read here (once per session_id)
...     tool calls          ← each carries x-mcp-startup-id
```

`headersHelper` fires exactly once per claude process. SessionStart
fires again on `/clear`, `/compact`, and `/resume` — with the same
PPID but a fresh `session_id` — so one `mcp_startup_id` accumulates
multiple `session_id` rows over the lifetime of a Claude Code
launch.

### Ordering caveat

MCP init runs before the SessionStart hook fires, so any scheme
where the *hook* mints the id and the *helper* reads it will not
work — the helper has already sent its first requests by the time
the hook can write anything. That's why the direction is
helper-writes / hook-reads.

### Concurrency

Two Claude Code sessions running simultaneously each have a unique
claude PID, which becomes the rendezvous filename's PPID suffix, so
they never collide.

## Component notes worth stashing

- **Hook `hooks.json` shape** requires an outer `hooks` wrapper:
  `{"hooks": {"SessionStart": [{"hooks": [{"type":"command","command":"..."}]}]}}`.
  Without it the whole file is rejected with a schema error visible
  in `/plugin` → Errors.
- **Slash-command naming** is `plugin-name:command-name` — the file
  under `commands/plugincmd.md` shows up as
  `/reference-plugin:plugincmd`. Tab-completion is the fastest way
  to confirm.
- **`${CLAUDE_PLUGIN_ROOT}`** is substituted in plugin config strings
  and resolves to the plugin's install directory — used here to
  point the hook `command` at `hooks/session-start.sh` without
  hard-coding a path.
- **`headersHelper` output is cached** for the lifetime of the MCP
  connection: the same header value ships on every request, not
  re-evaluated per call.
- **`$ARGUMENTS` / `$0` / `$1`** in slash-command bodies are
  substituted by Claude Code (not bash) before the body is
  interpreted. Off-by-one gotcha: `$0` is the first user-provided
  arg, so `$1` is the *second* one.
