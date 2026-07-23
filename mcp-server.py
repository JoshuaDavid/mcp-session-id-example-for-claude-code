#!/usr/bin/env python3
import http.server, json, os, time
LOG = os.environ["LOG_FILE"]; PORT = int(os.environ["PORT"])

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


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _log(self,s):
        with open(LOG,"a") as f: f.write(f"{time.time():.3f} MCP {s}\n")
    def do_POST(self):
        n=int(self.headers.get("Content-Length","0"))
        body=self.rfile.read(n).decode() if n else ""
        req=json.loads(body); m=req.get("method"); rid=req.get("id")
        h=self.headers.get("x-from-plugin","(missing)")
        self._log(f"{m} x-from-plugin={h}")
        if m and m.startswith("notifications/"):
            self.send_response(202); self.end_headers(); return
        if m=="initialize": r={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"p","version":"0"}}
        elif m=="tools/list": r={"tools": TOOLS}
        elif m=="tools/call":
            params = req.get("params", {})
            name = params.get("name")
            args = params.get("arguments", {}) or {}
            if name == "call-tool":
                payload = args.get("payload", "")
                r = {"content": [{"type": "text", "text": f"received payload: {payload}"}], "isError": False}
            else:
                r = {"content": [{"type": "text", "text": f"unknown tool: {name}"}], "isError": True}
        elif m=="resources/list": r={"resources":[]}
        elif m=="prompts/list": r={"prompts":[]}
        else: r={}
        data=json.dumps({"jsonrpc":"2.0","id":rid,"result":r}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(data))); self.end_headers()
        self.wfile.write(data)
    def do_GET(self):
        h=self.headers.get("x-from-plugin","(missing)")
        self._log(f"GET x-from-plugin={h}")
        self.send_response(405); self.end_headers()
if __name__=="__main__":
    open(LOG,"w").close()
    http.server.HTTPServer(("127.0.0.1",PORT),H).serve_forever()
