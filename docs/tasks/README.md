# Issues Queue 📋

This directory contains the core data for the Task Agent queue.

> [!CAUTION]
> `mission.usv` and `datapackage.json` are managed by the `ta` CLI and are protected with a Read-Only attribute. **Do not attempt to edit them manually.** Use `ta` commands (e.g., `ta new`, `ta ingest`, `ta up/down`) to modify the queue.

## 📂 Subdirectories

- [**Mission Control**](./mission.usv): The prioritized list of issue slugs.
- [**Schema**](./datapackage.json): Metadata describing the mission file format.
- [**Pending**](./pending/): Issues ready for implementation.
- [**Draft**](./draft/): Issues in the design or refinement phase.
- [**Active**](./active/): Issues currently being worked on.
- [**Completed**](./completed/): Historical archive of finished tasks.

For more information on how to manage issues, see the [Workflow Documentation](../workflow/README.md).
