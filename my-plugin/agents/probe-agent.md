---
name: probe-agent
description: Test agent shipped by the plugin.
tools: Bash
---

You are a probe agent. When invoked, run this Bash command exactly:

python3 -c 'import time; print(f"{time.time():.3f}")' | awk '{print $0" PLUGIN_AGENT invoked"}' >> /tmp/refplugin-ZH8b/log

Then reply with: agent-done
