import os
import json
from pathlib import Path
from typing import Optional
from taskagent.manager import TaskAgent


def discover(start_path: Optional[Path] = None) -> TaskAgent:
    """
    Standard discovery mechanism for task-agent.

    Checks in order:
    1. TA_CONFIG_DIR environment variable.
    2. .ta-config.json in start_path or any parent.
    3. docs/issues/ directory in start_path or any parent.

    Returns:
        TaskAgent: Initialized manager for the discovered instance.
    """
    if os.environ.get("TA_CONFIG_DIR"):
        return TaskAgent()

    current = Path(start_path or Path.cwd()).absolute()

    while True:
        # Check for explicit config file
        config_file = current / ".ta-config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                if "issues_dir" in config:
                    return TaskAgent(config_dir=str(current / config["issues_dir"]))
            except Exception:
                pass

        # Check for standard folder
        issues_dir = current / "docs" / "issues"
        if issues_dir.exists() and issues_dir.is_dir():
            return TaskAgent(config_dir=str(issues_dir))

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback to default (which will create docs/issues in starting search dir if not found)
    # We use start_path or cwd as the base
    fallback_base = Path(start_path or Path.cwd()).absolute()
    return TaskAgent(config_dir=str(fallback_base / "docs" / "issues"))
