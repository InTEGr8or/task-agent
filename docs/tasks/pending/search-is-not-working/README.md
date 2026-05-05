# Search is not working

I am getting results like this:

---
❯ ta history

  ISSUE: systematic-field-validation-with-workflow-stage-metadata
  SLUG: systematic-field-validation-with-workflow-stage-metadata | PRIORITY: 0 | STATUS:
  completed
  FILE:
  /home/mstouffer/repos/turboheatweldingtools/turboship/docs/tasks/completed/2026/systemati
  c-field-validation-with-workflow-stage-metadata/README.md


                  Systematic Field Validation with Workflow Stage Metadata

Goal

Eliminate JSONPath drift by separating concerns:

 • JSON Schema = pure data shape (including nested structures)
 • Effect Schema = pure TypeScript types
 • JSONPath Mapping = separate mapping files using dot notation
 • PayloadGenerator = simplified merger (schema + mapping only)
 • Static Linting = build-time validation of mapping completeness

Status: ✅ COMPLETE - READY TO DEPLOY

✅ Phase 1: Create Mapping File Structure

 • Created lib/schemas/mappings/ directory
 • Created PrintStatusUpdateInputPass.mapping.json with dot notation mappings
 • NO error field in mapping → prevents $.error in normal flow tasks
 • NO taskToken in mapping → prevents $.taskToken error

✅ Phase 2: Simplify PayloadGenerator

 • Rewrote payload-generator.ts (~90 lines)

10:56:08 turboship   uat [1998?] is 📦 v0.1.0 via  v24.15.0 on ☁️  bizkite-support (us-east-1)
❯ ta search systematic-field-validation-with-workflow-stage-metadata
No issues match pattern 'systematic-field-validation-with-workflow-stage-metadata'.

10:56:15 turboship   uat [1998?] is 📦 v0.1.0 via  v24.15.0 on ☁️  bizkite-support (us-east-1)
❯ ta search systemic-field
No issues match pattern 'systemic-field'.

10:56:31 turboship   uat [1998?] is 📦 v0.1.0 via  v24.15.0 on ☁️  bizkite-support (us-east-1)
❯
---
