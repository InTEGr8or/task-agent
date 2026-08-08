import json
import os
from pathlib import Path
from typing import List, Optional, Any

from taskagent.importers.base import BaseImporter, ImportedTask, ImportResult


class ClaudeCodeImporter(BaseImporter):
    """Importer driver for Claude Code todo and task lists."""

    agent_type: str = "claude-code"

    def parse(self, raw_content: str, source: str = "unknown") -> ImportResult:
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
        """Parse Claude Code todo payloads (current V2 & legacy V1 formats)."""
        tasks: List[ImportedTask] = []

        if isinstance(data, dict):
            task_list = (
                data.get("todos") or data.get("tasks") or data.get("items") or []
            )
        elif isinstance(data, list):
            task_list = data
        else:
            task_list = []

        for idx, item in enumerate(task_list, 1):
            if isinstance(item, dict):
                task_id = str(item.get("id") or f"claude-{idx}")
                title = str(
                    item.get("content")
                    or item.get("title")
                    or item.get("text")
                    or item.get("subject")
                    or f"Todo {idx}"
                )
                status = str(
                    item.get("status")
                    or ("completed" if item.get("completed") else "pending")
                )
                desc = item.get("description") or item.get("details")

                tasks.append(
                    ImportedTask(
                        id=task_id,
                        title=title,
                        status=status,
                        description=str(desc) if desc else None,
                        metadata={"raw": item},
                    )
                )
            elif isinstance(item, str) and item.strip():
                tasks.append(
                    ImportedTask(
                        id=f"claude-{idx}",
                        title=item.strip(),
                        status="pending",
                    )
                )

        return tasks

    def _parse_markdown(self, text: str) -> List[ImportedTask]:
        """Fallback markdown checklist parser."""
        tasks: List[ImportedTask] = []
        idx = 1
        for line in text.splitlines():
            line_str = line.strip()
            if line_str.startswith("- [ ]") or line_str.startswith("* [ ]"):
                title = line_str[5:].strip()
                if title:
                    tasks.append(
                        ImportedTask(id=f"claude-{idx}", title=title, status="pending")
                    )
                    idx += 1
            elif line_str.startswith("- [x]") or line_str.startswith("* [x]"):
                title = line_str[5:].strip()
                if title:
                    tasks.append(
                        ImportedTask(
                            id=f"claude-{idx}", title=title, status="completed"
                        )
                    )
                    idx += 1

        return tasks

    def discover_and_extract(self) -> Optional[ImportResult]:
        """Discover Claude Code tasks from standard local path candidates."""
        candidates = [
            Path(os.path.expanduser("~/.claude/todos.json")),
            Path(os.path.expanduser("~/.claude/tasks.json")),
            Path(".claude/todos.json"),
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                try:
                    content = candidate.read_text(encoding="utf-8")
                    return self.parse(content, source=str(candidate))
                except Exception:
                    continue

        return None
