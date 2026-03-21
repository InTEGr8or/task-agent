# Implement ADK Sidecar Worker with Multi-Agent Architecture

Build the reference sidecar worker in sidecars/adk-worker/ using the Google Agent Development Kit (ADK).

Key Requirements:
1. Reference ADK Python samples: https://github.com/google/adk-samples/tree/main/python
2. Implement a Multi-Agent loop:
   - **Manager Agent**: Parses the task from TA_FILE, breaks it down into steps, and coordinates sub-agents.
   - **Worker Agent**: Performs the actual code modifications within the git worktree (TA_ROOT).
   - **Validator Agent**: Runs tests and linting to verify the changes.
3. Correction Loop: If the Validator fails, the Manager should instruct the Worker to fix the issues based on logs.
4. Finalization: Call 'ta done <slug>' only after the Validator gives a 'Pass' signal.
5. Environment: Use the TA_SLUG, TA_FILE, and TA_ROOT variables provided by 'ta run'.

---
**Completed in commit:** `95484c5`
