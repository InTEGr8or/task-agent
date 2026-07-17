---
created_at: 2026-04-10T11:38:54-07:00
blocked_by: sub-agent-observability-and-transparency
---

# Define Task Metadata Standard

Define the `meta.json` structure for storing sub-agent metadata in each task folder.

## Metadata Structure

```json
{
  "slug": "task-slug",
  "status": "pending | active | completed",
  "start_time": "ISO-8601",
  "end_time": "ISO-8601",
  "reasoning_trace": "logs/trace.log"
}
```

This will be stored in `docs/tasks/<status>/<slug>/meta.json`.

---
**Completed in commit:** `f29dec5`
