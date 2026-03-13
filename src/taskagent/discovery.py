import os
import json
from pathlib import Path
from typing import Optional
from taskagent.manager import TaskAgent
from dotenv import load_dotenv


def _handle_ejected_symlink(current_root: Path):
    """
    Checks for TA_EJECT_ISSUES and ensures docs/issues symlink is correct.
    This 'auto-heals' links in new worktrees or clones.
    """
    # Load .env from project root
    load_dotenv(current_root / ".env")

    eject_enabled = os.environ.get("TA_EJECT_ISSUES", "").lower() == "true"
    target_path_str = os.environ.get("TA_EJECTED_ISSUES_PATH")

    if not eject_enabled or not target_path_str:
        return

    target_path = Path(target_path_str).absolute()
    issues_link = current_root / "docs" / "issues"

    # Ensure parent (docs/) exists
    issues_link.parent.mkdir(parents=True, exist_ok=True)

    if issues_link.exists() or issues_link.is_symlink():
        # Check if it's already correct
        if issues_link.is_symlink() and str(issues_link.readlink()) == str(target_path):
            return
        # If it's a directory or broken symlink, we might need to be careful.
        # But if ejection is forced, we want the link.
        if issues_link.is_symlink():
            issues_link.unlink()
        elif issues_link.is_dir() and not any(issues_link.iterdir()):
            issues_link.rmdir()
        else:
            # It's a non-empty directory, we don't want to overwrite user data
            return

    # Create the absolute symlink
    try:
        os.symlink(str(target_path), str(issues_link))
    except Exception:
        pass


def discover(start_path: Optional[Path] = None) -> TaskAgent:
    """
    Standard discovery mechanism for task-agent.

    Checks in order:
    1. TA_CONFIG_DIR environment variable.
    2. .ta-config.json in start_path or any parent.
    3. pyproject.toml [tool.taskagent] in start_path or any parent.
    4. docs/issues/ directory in start_path or any parent.
    5. ~/.config/task-agent/settings.json (Global fallback)

    Returns:
        TaskAgent: Initialized manager for the discovered instance.
    """
    if os.environ.get("TA_CONFIG_DIR"):
        return TaskAgent()

    current = Path(start_path or Path.cwd()).absolute()
    search_root = current

    # We walk up to find the project root (where .git or pyproject.toml is)
    # to handle symlink healing.
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            _handle_ejected_symlink(current)
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    current = search_root
    while True:
        # 1. Check for explicit config file
        config_file = current / ".ta-config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
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
                    if ta_cfg and "issues_dir" in ta_cfg:
                        return TaskAgent(config_dir=str(current / ta_cfg["issues_dir"]))
            except Exception:
                # Fallback if tomllib is missing or parse fails
                pass

        # 3. Check for standard folder
        issues_dir = current / "docs" / "issues"
        if issues_dir.exists() and issues_dir.is_dir():
            return TaskAgent(config_dir=str(issues_dir))

        # Move up
        parent = current.parent
        if parent == current:
            break
        current = parent

    # 4. Check Global Config
    global_config = Path("~/.config/task-agent/settings.json").expanduser()
    if global_config.exists():
        try:
            config = json.loads(global_config.read_text())
            if "issues_dir" in config:
                return TaskAgent(config_dir=config["issues_dir"])
        except Exception:
            pass

    # Fallback to default (which will create docs/issues in starting search dir if not found)
    # We use start_path or cwd as the base
    fallback_base = Path(start_path or Path.cwd()).absolute()
    return TaskAgent(config_dir=str(fallback_base / "docs" / "issues"))
