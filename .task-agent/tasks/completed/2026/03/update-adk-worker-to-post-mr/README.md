---
created_at: 2026-03-22T13:51:44-07:00
blocked_by: implement-merge-request-queue
---

# Update ADK worker to post MR

Update 'sidecars/adk-worker/worker.py' to write a completion datagram to 'docs/tasks/mr/' upon successful validation, rather than immediately calling 'ta done'. This enables an asynchronous, reviewable workflow.

## Solution

Updated ADK worker to write completion datagrams to 'docs/tasks/mr/'.

---
**Completed in commit:** `1608999`
