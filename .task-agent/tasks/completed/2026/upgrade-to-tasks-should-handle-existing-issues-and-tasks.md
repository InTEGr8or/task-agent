# Upgrade to tasks should handle existing issues/ and tasks/

Some repos might have both tasks and issues directories.

Some repos might have both, because ta init may have been run before upgrading the issus to tasks.

So, really, I guess ta init should do the upgrade. It should move the issues/ to tasks/.

---
**Completed in commit:** `5611e72`
