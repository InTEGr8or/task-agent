import os
import json
import shutil
from pathlib import Path
from typing import Optional
from taskagent.manager import TaskAgent
from dotenv import load_dotenv


def _update_env_var(env_path: Path, key: str, value: str):
    """Set a key=value in .env, replacing existing value if present."""
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n")
        return
    lines = env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    env_path.write_text("\n".join(lines) + "\n")


def _handle_ejected_symlink(current_root: Path):
    """
    Checks for TA_EJECT_ISSUES and TA_EJECT_TASKS and ensures docs symlink is correct.
    This 'auto-heals' links in new worktrees or clones.
    Also migrates old sibling-directory ejections to .task-agent/tasks/.
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

    tasks_link = current_root / "docs" / "tasks"

    # Resolve to main repo root (handle .gwt worktrees)
    if current_root.parent.name == ".gwt":
        repo_root = current_root.parent.parent
    else:
        repo_root = current_root
    new_target = repo_root / ".task-agent" / "tasks"

    # --- Auto-migrate old sibling ejection to .task-agent/tasks/ ---
    if tasks_link.is_symlink():
        old_target = Path(tasks_link.readlink()).resolve()
        if old_target != new_target.resolve() and old_target.exists():
            # Old-style ejection detected — migrate
            if not new_target.exists():
                new_target.mkdir(parents=True, exist_ok=True)
                for item in old_target.iterdir():
                    shutil.move(str(item), str(new_target / item.name))

                # Update .env
                abs_new = str(new_target.resolve())
                _update_env_var(env_path, "TA_EJECTED_TASKS_PATH", abs_new)
                _update_env_var(env_path, "TA_EJECTED_ISSUES_PATH", abs_new)

                # Update .gitignore
                gitignore = current_root / ".gitignore"
                if (
                    gitignore.exists()
                    and ".task-agent/tasks/" not in gitignore.read_text()
                ):
                    with gitignore.open("a") as f:
                        f.write("\n.task-agent/tasks/\n")

                # Remove old sibling directory
                if old_target.exists():
                    shutil.rmtree(str(old_target))

                # Reload env vars to pick up new path
                if env_path.exists():
                    load_dotenv(env_path, override=True)
                    target_path_str = os.environ.get(
                        "TA_EJECTED_TASKS_PATH"
                    ) or os.environ.get("TA_EJECTED_ISSUES_PATH")

    # Reload env_path in case env_path was created during migration
    if not target_path_str and env_path.exists():
        load_dotenv(env_path)
        target_path_str = os.environ.get("TA_EJECTED_TASKS_PATH") or os.environ.get(
            "TA_EJECTED_ISSUES_PATH"
        )

    # Determine target_path
    if not eject_enabled or not target_path_str:
        target_path = new_target
    else:
        path_obj = Path(target_path_str).expanduser()
        if path_obj.is_absolute():
            target_path = path_obj
        else:
            target_path = (current_root / path_obj).resolve().absolute()
        # Ensure the target directory exists – create it if missing
        if not target_path.is_dir():
            if target_path.exists() or target_path.is_symlink():
                raise RuntimeError(
                    f"The ejection target path '{target_path}' exists but is not a directory. "
                    "Please delete it or configure a different path."
                )
            target_path.mkdir(parents=True, exist_ok=True)
            # Update env vars to point to the created path
            if env_path.exists():
                _update_env_var(
                    env_path, "TA_EJECTED_TASKS_PATH", str(target_path.resolve())
                )
                _update_env_var(
                    env_path, "TA_EJECTED_ISSUES_PATH", str(target_path.resolve())
                )

    # Ensure target directory exists
    if not target_path.is_dir():
        if target_path.exists() or target_path.is_symlink():
            raise RuntimeError(
                f"The ejection target path '{target_path}' exists but is not a directory. "
                "Please delete it or configure a different path."
            )
        target_path.mkdir(parents=True, exist_ok=True)

    # Ensure parent (docs/) exists
    if not tasks_link.parent.is_dir():
        if tasks_link.parent.exists() or tasks_link.parent.is_symlink():
            raise RuntimeError(
                f"The path '{tasks_link.parent}' exists but is not a directory. "
                "Please delete it or configure a different path."
            )
        tasks_link.parent.mkdir(parents=True, exist_ok=True)

    if tasks_link.exists() or tasks_link.is_symlink():
        # Check if it's already correct
        if tasks_link.is_symlink() and str(tasks_link.readlink()) == str(target_path):
            return
        # If it's a directory or broken symlink, we might need to be careful.
        if tasks_link.is_symlink():
            tasks_link.unlink()
        elif tasks_link.is_dir() and not any(tasks_link.iterdir()):
            tasks_link.rmdir()
        else:
            # Recursive directory merge helper
            def _move_recursive(src: Path, dst: Path):
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                    for child in src.iterdir():
                        _move_recursive(child, dst / child.name)
                    src.rmdir()
                else:
                    if dst.exists():
                        dst.unlink()
                    shutil.move(str(src), str(dst))

            # Merge existing files into target, then remove tasks_link
            try:
                for item in tasks_link.iterdir():
                    if item.resolve() != target_path.resolve():
                        _move_recursive(item, target_path / item.name)
                tasks_link.rmdir()
            except Exception:
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

        # 3. Determine primary tasks directory (prefer docks/tasks, fallback to docs/tasks)
        docks_tasks = current / "docks" / "tasks"
        docs_tasks = current / "docs" / "tasks"
        # Choose existing directory or default to docks/tasks
        tasks_dir = docks_tasks if docks_tasks.exists() else docs_tasks
        if tasks_dir.exists() and tasks_dir.is_dir():
            # If using docks, ensure migration from old .task-agent if present
            if tasks_dir == docks_tasks:
                # Migrate any .task-agent/tasks content into docks/tasks
                old_task_root = current / ".task-agent" / "tasks"
                if old_task_root.exists() and old_task_root.is_dir():
                    for item in old_task_root.iterdir():
                        target_path = tasks_dir / item.name
                        if target_path.exists():
                            # If target exists, merge recursively
                            # Use same logic as later merge helper
                            # Simple move: overwrite if file, merge if dir
                            if item.is_dir() and target_path.is_dir():
                                # Recursive merge
                                for sub in item.rglob("*"):
                                    rel = sub.relative_to(item)
                                    dest = target_path / rel
                                    if sub.is_dir():
                                        dest.mkdir(parents=True, exist_ok=True)
                                    else:
                                        dest.parent.mkdir(parents=True, exist_ok=True)
                                        shutil.move(str(sub), str(dest))
                                shutil.rmtree(str(item))
                            else:
                                if target_path.is_dir():
                                    shutil.rmtree(str(target_path))
                                shutil.move(str(item), str(target_path))
                        else:
                            shutil.move(str(item), str(target_path))
                    # Clean up old .task-agent/tasks directory
                    try:
                        shutil.rmtree(str(old_task_root))
                    except Exception:
                        pass
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
