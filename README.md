# Claude Code reference plugin — MCP session-id workaround

**This plugin exists to demonstrate a working workaround for
[anthropics/claude-code#41836][issue] — "No session/conversation
identifier sent to MCP servers — cannot distinguish concurrent
sessions."**

NOTE THAT FOR THIS WORKAROUND TO BE USEFUL YOU MUST CONTROL THE HTTP MCP SERVER - though if you *don't* control the HTTP mcp server you probably also aren't doing anything special with a Claude Code Session ID header.

[issue]: https://github.com/anthropics/claude-code/issues/41836

## The problem, in one paragraph

When Claude Code talks to an HTTP MCP server, the wire protocol carries
no identifier for the Claude Code session behind the request. No
header, no URL parameter, no `clientInfo` field, no `_meta` entry —
verified empirically against Claude Code 2.1.133. `Mcp-Session-Id`
returned by the server on `initialize` is not echoed back on later
requests either. So an HTTP MCP server hit by multiple concurrent
Claude Code users has no wire-level way to attribute a tool call to
the conversation that made it, and cannot maintain per-conversation
state.

## The workaround this plugin demonstrates

Claude Code exposes two side channels that *can* see the session
identifier: the `SessionStart` hook (which receives it on stdin) and
the plugin's own shell environment (via `CLAUDE_CODE_SESSION_ID`).
Neither ships with the HTTP request, but we can bridge them:

1. When the MCP connection initializes, a `headersHelper` shell
   command mints a random `mcp_startup_id`, writes it to a rendezvous
   file keyed by claude's PID (`/tmp/refplugin-startup-$PPID`), and
   returns it as an `x-mcp-startup-id` HTTP header. This header ships
   on every request to the MCP endpoint for the lifetime of the
   connection.
2. Slightly later, the `SessionStart` hook fires. It's a direct child
   of the same claude process, so its `$PPID` matches the helper's.
   It reads the rendezvous file, receives the Claude Code
   `session_id` on stdin, and POSTs
   `{mcp_startup_id, claude_code_session_id, claude_code_pid, source}`
   to a `/register-session` endpoint on the server.
3. The server persists both halves and joins `tool_calls` to
   `sessions` on `mcp_startup_id` when rendering the dashboard.

Result: every HTTP MCP tool call is attributable to a specific
Claude Code session, without any changes to Claude Code itself.

Bonus: since the plugin has to demonstrate all this end-to-end, it
also happens to exercise every plugin component surface Claude Code
supports (MCP server, hook, slash command, skill, subagent), so it
doubles as a minimal reference for those.

## Layout

```
.
├── mcp-server.py          # standalone HTTP MCP server + dashboard
└── my-plugin/
    ├── .claude-plugin/
    │   └── plugin.json    # plugin manifest
    ├── .mcp.json          # MCP config: url + headersHelper
    ├── hooks/
    │   ├── hooks.json     # SessionStart hook registration
    │   └── session-start.sh
    ├── commands/
    │   └── plugincmd.md   # slash command (demo)
    ├── skills/
    │   └── probe-skill/
    │       └── SKILL.md   # skill (demo)
    └── agents/
        └── probe-agent.md # subagent (demo)
```

## Running it

Start the server:

```
LOG_FILE=/tmp/refplugin-log PORT=18796 python3 mcp-server.py
```

In another terminal, launch Claude Code with the plugin loaded:

```
claude --plugin-dir ./my-plugin
```

Ask Claude Code to call the tool ("call the plugin-mcp call-tool
with any payload"), then open http://127.0.0.1:18796/ — you'll see
the tool call attributed to the Claude Code session id that produced
it. That will look something like this:

<img width="488" height="801" alt="image" src="https://github.com/user-attachments/assets/865d7dca-3a9f-404f-a60a-ea6bc1de8125" />

## Exercising the other surfaces

The MCP correlation is the primary point, but the plugin also
demonstrates the other component types:

- **Slash command:** `/reference-plugin:plugincmd anything`. Plugin
  commands are namespaced `<plugin>:<command>`.
- **Skill:** `/probe-skill`. Skills use the bare skill name.
- **Subagent:** ask Claude Code to use the `probe-agent` subagent via
  the Agent tool. Subagents are not slash-invokable.
- **Hook:** fires automatically on every SessionStart (including
  after `/clear`, `/compact`, `/resume`).

## Timing details for the correlation

```
+0ms     MCP initialize        ← headersHelper runs here (once)
+~200ms  SessionStart hook     ← rendezvous read here
...      tool calls            ← each carries x-mcp-startup-id
```

`headersHelper` fires exactly once per claude process. `SessionStart`
fires again on `/clear`, `/compact`, and `/resume` — with the same
PPID but a fresh `session_id` — so one `mcp_startup_id` accumulates
multiple `session_id` rows over the lifetime of a Claude Code
launch.

**Ordering constraint.** MCP init runs before the SessionStart hook,
so any scheme where the *hook* mints the id and the *helper* reads
it will not work — the helper has already sent its first requests by
the time the hook can write anything. The direction has to be
helper-writes / hook-reads.

**Concurrency.** Two Claude Code sessions running simultaneously
each have a unique claude PID, which becomes the rendezvous
filename's suffix, so they never collide.

## Component gotchas worth stashing

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

## When this workaround stops being necessary

If [#41836][issue] ships — for example, Claude Code echoing back
`Mcp-Session-Id` per the MCP Streamable HTTP spec, or exposing a
Claude-scoped `X-Claude-Conversation-Id` header — the rendezvous
dance in this plugin becomes obsolete. The plugin components would
still be useful as component-surface examples, but the correlation
pattern itself is entirely a workaround for the missing wire-level
identifier.
