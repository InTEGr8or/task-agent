---
created_at: 2026-03-10T12:32:25-07:00
---

# Make sure \x1e is not used as a record separator anywhere

WE don't want to use the record separator instead of the newline or in addition to the newline. It causes too many parsing problems

---
**Completed in commit:** `c72a92c`
