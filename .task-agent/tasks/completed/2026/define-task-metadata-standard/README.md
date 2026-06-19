# Define Task Metadata Standard

**Depends on:** sub-agent-observability-and-transparency

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
