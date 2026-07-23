#!/usr/bin/env bash
# SessionStart hook: correlate this Claude Code session with the MCP startup id
# that headersHelper minted at MCP init time.
#
# Both this hook and the MCP headersHelper are direct children of the claude
# process, so they share the same PPID. headersHelper writes its minted id to
# a rendezvous file named by that PPID; this hook reads it back and POSTs the
# {claude_code_session_id, mcp_startup_id, claude_code_pid} triple to the
# server so the dashboard can join tool-call headers to sessions.

STDIN=$(cat)
PPID_VAL=$PPID
RENDEZVOUS="/tmp/refplugin-startup-${PPID_VAL}"
SERVER="http://127.0.0.1:18796"

# If MCP init hasn't fired yet (or the plugin's MCP isn't loaded), there's
# nothing to correlate. Exit silently.
[ -f "$RENDEZVOUS" ] || exit 0

MCP_STARTUP_ID=$(cat "$RENDEZVOUS")
SESSION_ID=$(printf '%s' "$STDIN" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("session_id",""))')
SOURCE=$(printf '%s' "$STDIN" | python3 -c 'import sys,json; d=json.loads(sys.stdin.read()); print(d.get("source",""))')

BODY=$(python3 -c "import json,sys; print(json.dumps({'mcp_startup_id': sys.argv[1], 'claude_code_session_id': sys.argv[2], 'claude_code_pid': int(sys.argv[3]), 'source': sys.argv[4]}))" "$MCP_STARTUP_ID" "$SESSION_ID" "$PPID_VAL" "$SOURCE")

curl -s -X POST "$SERVER/register-session" \
  -H "content-type: application/json" \
  -d "$BODY" >/dev/null || true
