---
name: probe-skill
description: Test skill shipped by the plugin. Records that it was invoked.
---

When invoked, write a marker to /tmp/refplugin-ZH8b/log using the Bash tool with:
```
python3 -c 'import time; print(f"{time.time():.3f}")' | awk '{print $0" PLUGIN_SKILL invoked"}' >> /tmp/refplugin-ZH8b/log
```

Then reply with only: skill-done
