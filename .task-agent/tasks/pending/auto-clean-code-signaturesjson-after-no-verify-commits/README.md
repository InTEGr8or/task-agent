---
created_at: 2026-06-14T10:03:52-07:00
---

# Auto-clean .code_signatures.json after no-verify commits

After a --no-verify commit, the pre-commit hook re-hashes .code_signatures.json on the next git status, leaving a dirty working tree. This is purely cosmetic but annoying — developers see a dirty tree even though they made no intentional changes.

Root cause:
The pre-commit hook's taskhash stage updates .code_signatures.json with expected hashes for the commit. When --no-verify skips hooks, this update never runs. On the next git status, the hook runs again and regenerates the file (because the tracked content changed), which makes it appear as a modification.

Observed behavior:
$ git status
Changes not staged for commit:
  modified:   .code_signatures.json

$ git diff .code_signatures.json
--- a/.code_signatures.json
+++ b/.code_signatures.json
@@ -1,7 +1,7 @@
 {
-  src/foo.py: abc123...,
-  src/bar.py: def456...,
+  src/foo.py: xyz789...,
+  src/bar.py: uvw012...,

Note the hashes themselves differ because the file was committed without updating, so the post-commit diff shows stale vs fresh hashes.

Solutions considered:
a) Add .code_signatures.json to .gitignore (loses hash tracking entirely — bad idea)
b) Auto-stage .code_signatures.json after every --no-verify commit (could cause noise in git log)
c) Run just the taskhash hook explicitly after --no-verify commits (targeted fix)
d) Suppress the file from git status via .git/info/exclude (doesn't fix the diff)

Preferred approach: Option (c). After ta done completes a --no-verify commit, explicitly run pre-commit run taskhash --files or equivalent to regenerate .code_signatures.json, then stage it as part of the original commit (ammend) or as a follow-up commit.

Actually, amending is problematic if the commit was already pushed. The simplest robust approach: add a .gitattributes entry to mark .code_signatures.json as linguist-generated=true (cosmetic), AND after a --no-verify commit, run the hash regeneration and auto-stage it so git status stays clean.

Implementation:
1. After the git commit in complete_issue(), detect if --no-verify was used (or always)
2. Run the equivalent of pre-commit run taskhash --all-files to regenerate
3. If .code_signatures.json changed, stage and amend the commit (only if not pushed)

Alternative simpler approach:
Add .code_signatures.json to .git/info/exclude so it's never tracked by git status. The file still exists and is versioned, but doesn't show as dirty. This is a band-aid but requires zero code changes.

Completion Criteria:
- Investigate and document root cause
- Implement fix: either auto-regeneration or git exclusion
- Verify git status stays clean after ta done --no-verify
- All existing tests pass
