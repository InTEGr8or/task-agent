# Update ADK worker to post MR

**Depends on:** implement-merge-request-queue

Update 'sidecars/adk-worker/worker.py' to write a completion datagram to 'docs/tasks/mr/' upon successful validation, rather than immediately calling 'ta done'. This enables an asynchronous, reviewable workflow.
