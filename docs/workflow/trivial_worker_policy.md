# Trivial Task Eligibility & Quality Gates Policy

This document defines the policy for autonomous background workers processing trivial tasks with cheap LLM models.

---

## 1. Trivial Task Eligibility

A task is considered **trivial-eligible** for automated background execution only if it meets all of the following machine-checkable criteria:

1. **Explicit Opt-in / Worker Tag**: The task frontmatter or description contains `worker: trivial` or has a `trivial` tag/label.
2. **Clear & Unambiguous Scope**: The task has explicit completion criteria and does not require design choices or architecture decisions.
3. **Scoped Scope/Paths**: Changes are limited to scoped, non-critical files (e.g. single-file fixes, doc updates, helper function additions, unit test additions).
4. **No Security Risks**: Does not touch auth, credentials, core security modules, or payment logic.
5. **Existing Test Coverage**: The target area already has existing tests that validate surrounding behavior.

### Examples

| Task Type | Trivial Eligible? | Reason |
|-----------|-------------------|--------|
| Add unit test for helper function | ✅ Yes | Scoped, low-risk, verified by test suite |
| Update CLI documentation for `ta prompt` | ✅ Yes | Doc update, clear scope |
| Fix typo in log message / error text | ✅ Yes | Low-risk, non-functional/cosmetic |
| Re-architect store registry model | ❌ No | Requires architecture design choices |
| Refactor authentication flow | ❌ No | Touches security/auth boundaries |

---

## 2. Hard Quality Gates

The worker pipeline MUST enforce strict automated quality gates:

1. **Pre-flight Check**: Baseline tests and linters must pass in the worktree before the cheap model makes edits.
2. **Maximum Attempts**: The cheap model has a strict limit of **1 to 2 attempts** to generate code and fix lint/test errors.
3. **Zero Tolerance**: 100% of existing tests and new/modified tests must pass. No swallowed errors or skipped assertions allowed.

---

## 3. Abort & Fail-Safe Behavior

When a quality gate fails after maximum attempts:

1. **Immediate Abort**: Stop execution immediately. Do NOT enter continuous retry loops or thrash the codebase.
2. **Cleanup Isolation**: Completely delete the temporary git worktree and branch.
3. **State Preservation**: The task MUST remain in `pending` (or marked `failed-trivial`) and NEVER marked `completed`.
4. **Inbox Notification**: Send a diagnostic message to the task inbox or task document detailing the failure log and reason for human review.
