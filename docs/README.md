# Task Agent Documentation 🤖

Welcome to the comprehensive documentation for **Task Agent**, a prioritized, file-based task queue designed for autonomous agentic workers and human-in-the-loop workflows.

## 📖 Table of Contents

- [**Architecture**](./architecture/README.md)
  - Understand the system design, folder structure, and data formats (USV).
- [**CLI Reference**](./cli/README.md)
  - Complete guide to the `ta` command-line interface.
- [**Workflow**](./workflow/README.md)
  - Best practices for managing tasks from draft to completion.
- [**Development**](./development/README.md)
  - Information on project setup, testing, and release processes.

## 🚀 Quick Start

To see what's currently at the top of your queue:
```bash
ta next
```

To create a new task:
```bash
ta new "Implement new feature" -b "Detailed description here"
```

To list all pending tasks:
```bash
ta list
```

## 📂 Project Structure

Task Agent operates directly on your filesystem, primarily within the `docs/tasks/` directory.

- `docs/tasks/mission.usv`: The source of truth for task priority.
- `docs/tasks/pending/`: Tasks ready for execution.
- `docs/tasks/draft/`: Tasks currently being refined.
- `docs/tasks/active/`: Tasks currently being worked on.
- `docs/tasks/completed/`: Historical record of finished work.

