import json
import os
from pathlib import Path
from typing import List, Optional, Any

from taskagent.importers.base import BaseImporter, ImportedTask, ImportResult


class AntigravityImporter(BaseImporter):
    """Importer driver for Antigravity CLI TaskManager task lists."""

    agent_type: str = "antigravity"

    def parse(self, raw_content: str, source: str = "unknown") -> ImportResult:
        tasks: List[ImportedTask] = []

        # Try parsing structured JSON payload
        try:
            data = json.loads(raw_content)
            tasks = self._parse_json(data)
        except json.JSONDecodeError:
            # Fallback to parsing line-by-line or Markdown task checklist
            tasks = self._parse_markdown(raw_content)

        return ImportResult(
            agent_type=self.agent_type,
            tasks=tasks,
            source=source,
        )

    def _parse_json(self, data: Any) -> List[ImportedTask]:
        """Version-tolerant JSON parser (V2 current schema + V1 legacy fallback)."""
        tasks: List[ImportedTask] = []

        # Case 1: Wrapped dict payload {"tasks": [...]}
        if isinstance(data, dict):
            task_list = data.get("tasks") or data.get("items") or data.get("todo") or []
        elif isinstance(data, list):
            task_list = data
        else:
            task_list = []

        for idx, item in enumerate(task_list, 1):
            if isinstance(item, dict):
                # V2 Schema fields
                task_id = str(item.get("id") or item.get("slug") or f"ag-{idx}")
                title = str(
                    item.get("title")
                    or item.get("name")
                    or item.get("text")
                    or item.get("summary")
                    or f"Task {idx}"
                )
                status = str(
                    item.get("status")
                    or item.get("state")
                    or ("completed" if item.get("done") else "pending")
                )
                desc = (
                    item.get("description") or item.get("details") or item.get("body")
                )
                created_at = item.get("created_at") or item.get("createdAt")

                tasks.append(
                    ImportedTask(
                        id=task_id,
                        title=title,
                        status=status,
                        description=str(desc) if desc else None,
                        created_at=str(created_at) if created_at else None,
                        metadata={"raw": item},
                    )
                )
            elif isinstance(item, str) and item.strip():
                # Legacy V1 string array fallback
                tasks.append(
                    ImportedTask(
                        id=f"ag-{idx}",
                        title=item.strip(),
                        status="pending",
                    )
                )

        return tasks

    def _parse_markdown(self, text: str) -> List[ImportedTask]:
        """Fallback parser for markdown checklist lines: - [ ] Task title."""
        tasks: List[ImportedTask] = []
        idx = 1
        for line in text.splitlines():
            line_str = line.strip()
            if line_str.startswith("- [ ]") or line_str.startswith("* [ ]"):
                title = line_str[5:].strip()
                if title:
                    tasks.append(
                        ImportedTask(id=f"ag-{idx}", title=title, status="pending")
                    )
                    idx += 1
            elif (
                line_str.startswith("- [x]")
                or line_str.startswith("* [x]")
                or line_str.startswith("- [X]")
            ):
                title = line_str[5:].strip()
                if title:
                    tasks.append(
                        ImportedTask(id=f"ag-{idx}", title=title, status="completed")
                    )
                    idx += 1

        return tasks

    def discover_and_extract(self) -> Optional[ImportResult]:
        """Discover Antigravity tasks from home directory or environment app data."""
        candidates = [
            Path(os.path.expanduser("~/.gemini/antigravity-cli/tasks.json")),
            Path(os.path.expanduser("~/.gemini/tasks.json")),
            Path(".gemini/tasks.json"),
        ]

        # Check APP_DATA_DIR if set
        app_data = os.environ.get("ANTIGRAVITY_APP_DATA_DIR")
        if app_data:
            candidates.insert(0, Path(app_data) / "tasks.json")

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                    return self.parse(content, source=str(candidate))
                except Exception:
                    continue

        return None
