import json
from typing import List, Optional, Any

from taskagent.importers.base import BaseImporter, ImportedTask, ImportResult


class GenericImporter(BaseImporter):
    """Generic importer for arbitrary JSON or Markdown task payloads."""

    agent_type: str = "generic"

    def parse(self, raw_content: str, source: str = "raw_input") -> ImportResult:
        tasks: List[ImportedTask] = []

        try:
            data = json.loads(raw_content)
            tasks = self._parse_json(data)
        except json.JSONDecodeError:
            tasks = self._parse_markdown(raw_content)

        return ImportResult(
            agent_type=self.agent_type,
            tasks=tasks,
            source=source,
        )

    def _parse_json(self, data: Any) -> List[ImportedTask]:
        tasks: List[ImportedTask] = []
        if isinstance(data, dict):
            task_list = (
                data.get("tasks") or data.get("items") or data.get("todos") or []
            )
        elif isinstance(data, list):
            task_list = data
        else:
            task_list = []

        for idx, item in enumerate(task_list, 1):
            if isinstance(item, dict):
                title = str(
                    item.get("title")
                    or item.get("name")
                    or item.get("content")
                    or item.get("text")
                    or f"Item {idx}"
                )
                status = str(
                    item.get("status")
                    or (
                        "completed"
                        if item.get("done") or item.get("completed")
                        else "pending"
                    )
                )
                desc = item.get("description") or item.get("details")

                tasks.append(
                    ImportedTask(
                        id=str(item.get("id") or f"item-{idx}"),
                        title=title,
                        status=status,
                        description=str(desc) if desc else None,
                        metadata={"raw": item},
                    )
                )
            elif isinstance(item, str) and item.strip():
                tasks.append(
                    ImportedTask(id=f"item-{idx}", title=item.strip(), status="pending")
                )

        return tasks

    def _parse_markdown(self, text: str) -> List[ImportedTask]:
        tasks: List[ImportedTask] = []
        idx = 1
        for line in text.splitlines():
            line_str = line.strip()
            if line_str.startswith("- [ ]") or line_str.startswith("* [ ]"):
                title = line_str[5:].strip()
                if title:
                    tasks.append(
                        ImportedTask(id=f"task-{idx}", title=title, status="pending")
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
                        ImportedTask(id=f"task-{idx}", title=title, status="completed")
                    )
                    idx += 1

        return tasks

    def discover_and_extract(self) -> Optional[ImportResult]:
        return None
