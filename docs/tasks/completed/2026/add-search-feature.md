# Add search feature

The user should be able to search for a task

task-agent should search by slug.

It should match by the begining of the slug, so pattern match with a wildcard end.

If one task is found, task-agent should present that task in view mode and allow edit mode from the view.

If multiple match, present a navigable list and use `l` to select one for viewing, and `h` to go back to the list.

`q` to exit.

---
**Completed in commit:** `2f481c0`
