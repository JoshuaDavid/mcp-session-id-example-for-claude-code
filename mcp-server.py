#!/usr/bin/env python3
import http.server, json, os, sqlite3, time, html

LOG = os.environ.get("LOG_FILE", "/tmp/refplugin-log")
PORT = int(os.environ.get("PORT", "18796"))
DB = os.environ.get("DB_FILE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sessions.sqlite"))

TOOLS = [
    {
        "name": "call-tool",
        "description": "Reference tool exposed by the plugin's HTTP MCP server. Echoes back the payload it received.",
        "inputSchema": {
            "type": "object",
            "properties": {"payload": {"type": "string", "description": "Arbitrary string payload"}},
            "required": ["payload"],
        },
    },
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mcp_startup_id TEXT NOT NULL,
    claude_code_session_id TEXT NOT NULL,
    claude_code_pid INTEGER NOT NULL,
    source TEXT,
    registered_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_startup ON sessions(mcp_startup_id);
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mcp_startup_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    arguments_json TEXT NOT NULL,
    called_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_toolcalls_startup ON tool_calls(mcp_startup_id);
"""


def db():
    c = sqlite3.connect(DB)
    c.executescript(SCHEMA)
    return c


def log(s):
    with open(LOG, "a") as f:
        f.write(f"{time.time():.3f} MCP {s}\n")


def render_index() -> bytes:
    c = db()
    startups = [r[0] for r in c.execute(
        "SELECT DISTINCT mcp_startup_id FROM sessions "
        "UNION SELECT DISTINCT mcp_startup_id FROM tool_calls"
    ).fetchall()]
    rows = []
    for sid in startups:
        sess = c.execute(
            "SELECT claude_code_session_id, claude_code_pid, source, registered_at "
            "FROM sessions WHERE mcp_startup_id=? ORDER BY registered_at",
            (sid,),
        ).fetchall()
        calls = c.execute(
            "SELECT tool_name, arguments_json, called_at FROM tool_calls "
            "WHERE mcp_startup_id=? ORDER BY called_at",
            (sid,),
        ).fetchall()
        rows.append((sid, sess, calls))
    c.close()

    parts = [
        "<!doctype html><meta charset=utf-8><title>Reference MCP dashboard</title>",
        "<style>body{font:14px/1.4 system-ui,sans-serif;margin:2rem;max-width:1100px}"
        "h1{margin-top:0}h2{margin-top:2rem;border-bottom:1px solid #ddd;padding-bottom:.3rem}"
        "table{border-collapse:collapse;margin:.5rem 0}th,td{border:1px solid #ccc;padding:.3rem .6rem;text-align:left;vertical-align:top}"
        "th{background:#f4f4f4}code{background:#f4f4f4;padding:0 .2rem;border-radius:3px}"
        ".empty{color:#999;font-style:italic}</style>",
        "<h1>Reference MCP dashboard</h1>",
        f"<p>DB: <code>{html.escape(DB)}</code>. {len(rows)} MCP startup(s) observed.</p>",
    ]
    if not rows:
        parts.append("<p class=empty>No sessions recorded yet. Launch a Claude Code session with the plugin loaded, then reload.</p>")
    for sid, sess, calls in rows:
        parts.append(f"<h2>mcp_startup_id: <code>{html.escape(sid)}</code></h2>")
        if sess:
            parts.append("<table><tr><th>claude_code_session_id</th><th>claude_code_pid</th><th>source</th><th>registered_at</th></tr>")
            for scc, pid, src, ts in sess:
                parts.append(
                    f"<tr><td><code>{html.escape(scc)}</code></td>"
                    f"<td>{pid}</td><td>{html.escape(src or '')}</td>"
                    f"<td>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p class=empty>No SessionStart correlations registered for this startup id.</p>")
        parts.append("<h3>Tool calls</h3>")
        if calls:
            parts.append("<table><tr><th>tool</th><th>arguments</th><th>called_at</th></tr>")
            for name, args, ts in calls:
                parts.append(
                    f"<tr><td><code>{html.escape(name)}</code></td>"
                    f"<td><code>{html.escape(args)}</code></td>"
                    f"<td>{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}</td></tr>"
                )
            parts.append("</table>")
        else:
            parts.append("<p class=empty>No tool calls yet.</p>")
    return "".join(parts).encode()


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _respond(self, code, body=b"", ct="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._respond(200, render_index(), "text/html; charset=utf-8"); return
        if self.path.rstrip("/") == "/mcp":
            # streamable-http subscribe; we don't push events, just accept and 405 the SSE
            self._respond(405); return
        self._respond(404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(n).decode() if n else ""
        if self.path.rstrip("/") == "/mcp":
            self._handle_mcp(body); return
        self._respond(404)

    def _handle_mcp(self, body):
        try:
            req = json.loads(body)
        except Exception:
            self._respond(400); return
        m = req.get("method"); rid = req.get("id")
        startup_id = self.headers.get("x-mcp-startup-id", "(missing)")
        log(f"{m} startup={startup_id}")

        if m and m.startswith("notifications/"):
            self._respond(202); return

        if m == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "reference-plugin-mcp", "version": "0.0.1"}}
        elif m == "tools/list":
            result = {"tools": TOOLS}
        elif m == "tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            c = db()
            c.execute(
                "INSERT INTO tool_calls(mcp_startup_id, tool_name, arguments_json, called_at) VALUES (?, ?, ?, ?)",
                (startup_id, name, json.dumps(args), time.time()),
            )
            c.commit(); c.close()
            if name == "call-tool":
                result = {"content": [{"type": "text", "text": f"received payload: {args.get('payload','')}"}], "isError": False}
            else:
                result = {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
        elif m == "resources/list":
            result = {"resources": []}
        elif m == "prompts/list":
            result = {"prompts": []}
        else:
            result = {}

        data = json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}).encode()
        self._respond(200, data, "application/json")


if __name__ == "__main__":
    open(LOG, "w").close()
    db().close()
    print(f"listening on http://127.0.0.1:{PORT}/  (MCP at /mcp, dashboard at /)")
    http.server.HTTPServer(("127.0.0.1", PORT), H).serve_forever()
