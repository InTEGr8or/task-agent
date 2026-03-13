import os
import json
from pathlib import Path
from typing import Optional
from taskagent.manager import TaskManager


def discover(start_path: Optional[Path] = None) -> TaskManager:
    """
    Standard discovery mechanism for task-agent.

    Checks in order:
    1. TA_CONFIG_DIR environment variable.
    2. .ta-config.json in start_path or any parent.
    3. docs/issues/ directory in start_path or any parent.

    Returns:
        TaskManager: Initialized manager for the discovered instance.
    """
    if os.environ.get("TA_CONFIG_DIR"):
        return TaskManager()

    current = Path(start_path or Path.cwd()).absolute()

    while True:
        # Check for explicit config file
        config_file = current / ".ta-config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                if "issues_dir" in config:
                    return TaskManager(config_dir=str(current / config["issues_dir"]))
            except Exception:
                pass

        # Check for standard folder
        issues_dir = current / "docs" / "issues"
        if issues_dir.exists() and issues_dir.is_dir():
            return TaskManager(config_dir=str(issues_dir))

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Fallback to default (which will create docs/issues in current dir if not found)
    return TaskManager()
