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


def _repo_root_for(path: Path) -> Path:
    """Map a path to its main repo root (unwrap .gwt / git worktrees).

    Delegates to store_registry.project_host_root so discovery and migrate
    agree on where the legacy task store lives.
    """
    from taskagent.store_registry import project_host_root

    return project_host_root(path)


def _heal_docs_tasks_symlink(root: Path, target: Path) -> None:
    """Ensure docs/tasks points at target when human symlink preference is on.

    Only manages ``docs/tasks`` (human convenience). Respects
    ``store_symlink: false`` in ``.ta-config.json`` so ``ta store symlink off``
    is not undone by discovery auto-heal.

    Non-destructive: only creates/replaces missing, empty, or symlink links.
    Does not merge a populated real directory.
    """
    from taskagent.store_registry import store_symlink_preferred

    if not store_symlink_preferred(root):
        return

    target_abs = target.resolve()
    link = root / "docs" / "tasks"
    parent = link.parent
    if not parent.is_dir():
        if parent.exists() or parent.is_symlink():
            return
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

    try:
        if link.is_symlink() and link.resolve() == target_abs:
            return
        if link.is_symlink():
            link.unlink()
        elif link.is_dir():
            if any(link.iterdir()):
                return  # leave populated trees alone
            link.rmdir()
        elif link.exists():
            return
        os.symlink(str(target_abs), str(link))
    except OSError:
        pass


def _resolve_centralized_store(
    host_path: Path, moniker_override: Optional[str] = None
) -> Optional[Path]:
    """Return an existing machine data-root store for this host, if any.

    Resolution:
    1. Explicit moniker override (env / config)
    2. Registry entry by moniker or host path
    3. Canonical path under data root for derived moniker
    """
    from taskagent.store_registry import (
        MachineRegistry,
        looks_like_store,
        resolve_moniker_for_host,
        store_path_for_moniker,
    )

    host = _repo_root_for(host_path.expanduser().resolve())
    moniker = moniker_override
    if not moniker:
        moniker, _ = resolve_moniker_for_host(host)

    reg = MachineRegistry()
    entry = reg.get(moniker) if moniker else None
    if entry is None:
        entry = reg.find_by_host_path(host)

    candidates = []
    if entry:
        candidates.append(Path(entry.store_path))
    if moniker:
        candidates.append(store_path_for_moniker(moniker))

    seen = set()
    for cand in candidates:
        try:
            resolved = cand.expanduser().resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if resolved.is_dir() and looks_like_store(resolved):
            return resolved
    return None


def _handle_ejected_symlink(current_root: Path):
    """
    Checks for TA_EJECT_ISSUES and TA_EJECT_TASKS and ensures docs symlink is correct.
    This 'auto-heals' links in new worktrees or clones.
    Also migrates old sibling-directory ejections to .task-agent/tasks/.

    Prefer centralized data-root store when one already exists for this host
    (Phase 3); otherwise keep legacy eject defaults for unmigrated projects.
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
    repo_root = _repo_root_for(current_root)
    new_target = repo_root / ".task-agent" / "tasks"

    # Phase 3: if a centralized store already exists, prefer it.
    # Do **not** create or heal ``.task-agent/tasks`` — that eject path is
    # legacy; moniker/registry resolve the data-root store. Optional docs/tasks
    # human symlink is controlled by store_symlink preference.
    moniker_override = os.environ.get("TA_STORE_MONIKER") or None
    centralized = _resolve_centralized_store(repo_root, moniker_override)
    if centralized is not None:
        if env_path.exists() or eject_enabled or target_path_str:
            env_file = env_path if env_path.exists() else (repo_root / ".env")
            _update_env_var(env_file, "TA_EJECT_TASKS", "true")
            _update_env_var(
                env_file, "TA_EJECTED_TASKS_PATH", str(centralized.resolve())
            )
            _update_env_var(
                env_file, "TA_EJECTED_ISSUES_PATH", str(centralized.resolve())
            )
        _heal_docs_tasks_symlink(current_root, centralized)
        return

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
    1. ``TA_CONFIG_DIR`` environment variable.
    2. ``TA_STORE_MONIKER`` → existing machine data-root store.
    3. Repo-bound centralized store (registry / canonical moniker path).
    4. ``.ta-config.json`` (``store_moniker``, ``tasks_dir``, ``issues_dir``).
    5. ``pyproject.toml`` ``[tool.taskagent]``.
    6. Legacy eject heal + ``docs/tasks`` / ``docks/tasks``.
    7. ``docs/issues/`` (legacy).
    8. ``~/.config/task-agent/settings.json``.
    9. Fallback: create ``docs/tasks`` under start path (non-repo) or eject path.

    Returns:
        TaskAgent: Initialized manager for the discovered instance.
    """
    if os.environ.get("TA_CONFIG_DIR"):
        return TaskAgent()

    # Explicit moniker override (may resolve before walking)
    moniker_env = os.environ.get("TA_STORE_MONIKER")
    if moniker_env:
        central = _resolve_centralized_store(Path.cwd(), moniker_env)
        if central is not None:
            return TaskAgent(config_dir=str(central))

    current = Path(start_path or Path.cwd()).absolute()
    search_root = current

    repo_boundary = None
    while True:
        if (current / ".git").exists() or (current / "pyproject.toml").exists():
            repo_boundary = current
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Phase 3: prefer existing data-root store for this host before legacy eject.
    # Migrated hosts bind via moniker/registry only — no .task-agent/tasks heal.
    if repo_boundary is not None:
        central = _resolve_centralized_store(repo_boundary, moniker_env)
        if central is not None:
            _heal_docs_tasks_symlink(repo_boundary, central)
            return TaskAgent(config_dir=str(central))

        # Unmigrated: keep legacy eject auto-heal
        _handle_ejected_symlink(repo_boundary)

    current = search_root
    while True:
        if repo_boundary and not current.is_relative_to(repo_boundary):
            break

        # 1. Check for explicit config file
        config_file = current / ".ta-config.json"
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text())
                moniker = config.get("store_moniker") or config.get("moniker")
                if moniker:
                    central = _resolve_centralized_store(current, str(moniker))
                    if central is not None:
                        return TaskAgent(config_dir=str(central))
                if "tasks_dir" in config:
                    tasks_cfg = Path(config["tasks_dir"])
                    path = tasks_cfg if tasks_cfg.is_absolute() else current / tasks_cfg
                    return TaskAgent(config_dir=str(path))
                if "issues_dir" in config:
                    issues_cfg = Path(config["issues_dir"])
                    path = (
                        issues_cfg if issues_cfg.is_absolute() else current / issues_cfg
                    )
                    return TaskAgent(config_dir=str(path))
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
                        moniker = ta_cfg.get("store_moniker") or ta_cfg.get("moniker")
                        if moniker:
                            central = _resolve_centralized_store(current, str(moniker))
                            if central is not None:
                                return TaskAgent(config_dir=str(central))
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
                if (
                    old_task_root.exists()
                    and old_task_root.is_dir()
                    and not old_task_root.is_symlink()
                ):
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
            # If docs/tasks is a symlink into a store, use resolved path
            try:
                resolved_tasks = tasks_dir.resolve()
            except OSError:
                resolved_tasks = tasks_dir
            # Check if mission files are in .task-agent/ subdirectory
            if (resolved_tasks / ".task-agent").exists():
                return TaskAgent(config_dir=str(resolved_tasks))
            # Check if old structure (mission files in tasks root) - will auto-migrate
            elif (resolved_tasks / "mission.usv").exists() or (
                resolved_tasks / "datapackage.json"
            ).exists():
                return TaskAgent(config_dir=str(resolved_tasks))
            # Empty tasks dir - still return it
            return TaskAgent(config_dir=str(resolved_tasks))

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


def get_task_agent_project_root() -> Path:
    """Find the root directory of the task-agent repository.

    Tries multiple resolution strategies:
    1. Check if the current file's package path resolves to a directory containing docs/tasks.
    2. Check the uv-receipt.toml for the task-agent tool to find its source directory.
    3. Fall back to standard/well-known directories (e.g. ~/repos/task-agent).
    """
    # Strategy 1: Dev / editable installation
    dev_root = Path(__file__).resolve().parent.parent.parent
    if (dev_root / "docs" / "tasks").exists():
        return dev_root

    # Strategy 2: Parse uv-receipt.toml
    uv_receipt = Path("~/.local/share/uv/tools/task-agent/uv-receipt.toml").expanduser()
    if uv_receipt.exists():
        try:
            content = uv_receipt.read_text()
            # Simple regex parser to extract directory
            import re

            m = re.search(r'directory\s*=\s*"([^"]+)"', content)
            if m:
                receipt_path = Path(m.group(1))
                if (receipt_path / "docs" / "tasks").exists():
                    return receipt_path
        except Exception:
            pass

    # Strategy 3: Fall back to well-known directory
    fallback = Path("~/repos/task-agent").expanduser()
    if (fallback / "docs" / "tasks").exists():
        return fallback

    return dev_root
