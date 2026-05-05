import os
import json
from pathlib import Path
from typing import Optional
from taskagent.manager import TaskAgent
from dotenv import load_dotenv


def _handle_ejected_symlink(current_root: Path):
    """
    Checks for TA_EJECT_ISSUES and TA_EJECT_TASKS and ensures docs symlink is correct.
    This 'auto-heals' links in new worktrees or clones.
    """
    # 1. Try to find the primary .env
    # If we are in a worktree (.gwt/something), look in the parent project root
    env_path = current_root / ".env"
    if not env_path.exists() and current_root.parent.name == ".gwt":
        # We are in a task-agent managed worktree
        env_path = current_root.parent.parent / ".env"

    if env_path.exists():
        load_dotenv(env_path)

    # Support both TA_EJECT_ISSUES and TA_EJECT_TASKS
    eject_enabled = (
        os.environ.get("TA_EJECT_TASKS", "").lower() == "true"
        or os.environ.get("TA_EJECT_ISSUES", "").lower() == "true"
    )
    target_path_str = os.environ.get("TA_EJECTED_TASKS_PATH") or os.environ.get(
        "TA_EJECTED_ISSUES_PATH"
    )

    if not eject_enabled or not target_path_str:
        return

    target_path = Path(target_path_str).absolute()
    tasks_link = current_root / "docs" / "tasks"

    # Ensure parent (docs/) exists
    tasks_link.parent.mkdir(parents=True, exist_ok=True)

    if tasks_link.exists() or tasks_link.is_symlink():
        # Check if it's already correct
        if tasks_link.is_symlink() and str(tasks_link.readlink()) == str(target_path):
            return
        # If it's a directory or broken symlink, we might need to be careful.
        # But if ejection is forced, we want the link.
        if tasks_link.is_symlink():
            tasks_link.unlink()
        elif tasks_link.is_dir() and not any(tasks_link.iterdir()):
            tasks_link.rmdir()
        else:
            # It's a non-empty directory, we don't want to overwrite user data
            return

    # Create the absolute symlink
    try:
        os.symlink(str(target_path), str(tasks_link))
    except Exception:
        pass


def discover(start_path: Optional[Path] = None) -> TaskAgent:
    """
    Standard discovery mechanism for task-agent.

    Checks in order:
    1. TA_CONFIG_DIR environment variable.
    2. .ta-config.json in start_path or any parent.
    3. pyproject.toml [tool.taskagent] in start_path or any parent.
    4. docs/tasks/ directory in start_path or any parent.
    5. docs/issues/ directory in start_path or any parent (legacy, for migration).
    6. ~/.config/task-agent/settings.json (Global fallback)

    Returns:
        TaskAgent: Initialized manager for the discovered instance.
    """
    if os.environ.get("TA_CONFIG_DIR"):
        return TaskAgent()

    current = Path(start_path or Path.cwd()).absolute()
    search_root = current

    repo_boundary = None
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            repo_boundary = current
            _handle_ejected_symlink(current)
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    current = search_root
    while True:
        if repo_boundary and not current.is_relative_to(repo_boundary):
            break

        # 1. Check for explicit config file
        config_file = current / ".ta-config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                if "tasks_dir" in config:
                    return TaskAgent(config_dir=str(current / config["tasks_dir"]))
                if "issues_dir" in config:
                    return TaskAgent(config_dir=str(current / config["issues_dir"]))
            except Exception:
                pass

        # 2. Check for pyproject.toml
        pyproject = current / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib

                with pyproject.open("rb") as f:
                    data = tomllib.load(f)
                    ta_cfg = data.get("tool", {}).get("taskagent")
                    if ta_cfg:
                        if "tasks_dir" in ta_cfg:
                            return TaskAgent(
                                config_dir=str(current / ta_cfg["tasks_dir"])
                            )
                        if "issues_dir" in ta_cfg:
                            return TaskAgent(
                                config_dir=str(current / ta_cfg["issues_dir"])
                            )
            except Exception:
                # Fallback if tomllib is missing or parse fails
                pass

        # 3. Check for docs/tasks/.task-agent/ (new default with mission files in subdirectory)
        tasks_dir = current / "docs" / "tasks"
        if tasks_dir.exists() and tasks_dir.is_dir():
            # Check if mission files are in .task-agent/ subdirectory
            if (tasks_dir / ".task-agent").exists():
                return TaskAgent(config_dir=str(tasks_dir))
            # Check if old structure (mission files in tasks root) - will auto-migrate
            elif (tasks_dir / "mission.usv").exists() or (
                tasks_dir / "datapackage.json"
            ).exists():
                return TaskAgent(config_dir=str(tasks_dir))
            # Empty tasks dir - still return it
            return TaskAgent(config_dir=str(tasks_dir))

        # 4. Check for docs/issues/ (legacy fallback for migration)
        issues_dir = current / "docs" / "issues"
        if issues_dir.exists() and issues_dir.is_dir():
            return TaskAgent(config_dir=str(issues_dir))

        if current == repo_boundary:
            break

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent

    # 5. Check Global Config
    global_config = Path("~/.config/task-agent/settings.json").expanduser()
    if global_config.exists():
        try:
            config = json.loads(global_config.read_text())
            if "tasks_dir" in config:
                return TaskAgent(config_dir=config["tasks_dir"])
            if "issues_dir" in config:
                return TaskAgent(config_dir=config["issues_dir"])
        except Exception:
            pass

    # Fallback to default (which will create docs/tasks in starting search dir if not found)
    # We use start_path or cwd as the base
    fallback_base = Path(start_path or Path.cwd()).absolute()
    return TaskAgent(config_dir=str(fallback_base / "docs" / "tasks"))
