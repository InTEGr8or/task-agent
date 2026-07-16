from typing import List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import re
import subprocess
import os
import shutil
import stat
import json

from taskagent.models.issue import Issue, USV_DELIM


class TaskAgent:
    def __init__(self, config_dir: Optional[str] = None):
        self.issues_root, self.mission_dir, self.mission_path = self.get_config_paths(
            config_dir
        )
        self.ensure_issues_dir()
        self.code_root = self._get_git_root(Path.cwd())
        self.mission_root = self._get_git_root(self.issues_root)

    @staticmethod
    def _get_git_root(path: Path) -> Optional[Path]:
        """Get the root of the git repository for the given path."""
        try:
            res = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=True,
                shell=(os.name == "nt"),
            )
            return Path(res.stdout.strip())
        except subprocess.CalledProcessError:
            return None

    @staticmethod
    def _check_dependency_cycle(
        issues: List[Issue], target_slug: str, new_deps: List[str]
    ) -> bool:
        """Check if adding new_deps to target_slug creates a cycle.

        Returns True if a cycle is detected, False otherwise.
        """
        dep_map = {i.slug: list(i.dependencies) for i in issues}
        dep_map[target_slug] = list(new_deps)
        visited = {}  # None: unvisited, 0: visiting, 1: visited

        def has_cycle(node: str) -> bool:
            visited[node] = 0
            for neighbor in dep_map.get(node, []):
                state = visited.get(neighbor)
                if state == 0:
                    return True
                elif state is None:
                    if has_cycle(neighbor):
                        return True
            visited[node] = 1
            return False

        for node in dep_map:
            if visited.get(node) is None:
                if has_cycle(node):
                    return True
        return False

    @property
    def is_dual_repo(self) -> bool:
        """Check if mission files live in a different repo than the code."""
        if not self.code_root or not self.mission_root:
            return False
        return self.code_root.resolve() != self.mission_root.resolve()

    def push_mission_repo(self):
        """Push changes in the mission repository."""
        if not self.mission_root:
            return
        try:
            subprocess.run(
                ["git", "-C", str(self.mission_root), "push"],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to push mission repository: {e.stderr}")

    def _set_writable(self, path: Path, writable: bool):
        """Toggle the filesystem write bit and chattr for a file."""
        if not path.exists():
            return

        import sys

        is_linux = sys.platform.startswith("linux")

        # First handle chattr (immutable attribute) on Linux
        if writable and is_linux:
            # Remove immutable attribute before making writable
            try:
                subprocess.run(
                    ["chattr", "-i", str(path)],
                    capture_output=True,
                    check=True,
                )
            except FileNotFoundError:
                pass  # chattr not available
            except subprocess.CalledProcessError:
                pass  # Ignore here; if chmod fails later, we will handle it

        # Handle chmod
        current_mode = path.stat().st_mode
        try:
            if writable:
                os.chmod(path, current_mode | stat.S_IWRITE)
            else:
                os.chmod(path, current_mode & ~stat.S_IWRITE)
        except PermissionError as e:
            if writable and is_linux:
                raise RuntimeError(
                    f"Cannot modify {path.name} (immutable attribute set or permission denied).\n"
                    f"Run: sudo chattr -i {path}\n"
                    f"Or: sudo setcap cap_linux_immutable+ep $(which ta)"
                ) from e
            raise

        # Set immutable attribute after making read-only on Linux
        if not writable and is_linux:
            try:
                subprocess.run(
                    ["chattr", "+i", str(path)],
                    capture_output=True,
                    check=False,
                )
            except Exception:
                pass  # Best effort

    @staticmethod
    def get_config_paths(config_dir: Optional[str] = None) -> Tuple[Path, Path, Path]:
        """Get the issues root, mission dir, and mission path based on config or environment."""
        if config_dir:
            issues_root = Path(config_dir)
        else:
            # Check environment variable, then default to docs/tasks
            env_dir = os.environ.get("TA_CONFIG_DIR")
            issues_root = Path(env_dir) if env_dir else Path("docs/tasks")

        mission_dir = issues_root / ".task-agent"
        mission_path = mission_dir / "mission.usv"
        return issues_root, mission_dir, mission_path

    @property
    def plan_path(self) -> Path:
        return self.issues_root / "plan.md"

    def get_or_create_plan(self) -> Path:
        path = self.plan_path
        if not path.exists():
            path.write_text(
                "# Plan\n\n*Long-term strategy and direction for this project.*\n"
            )
        return path

    def ensure_issues_dir(self):
        """Ensure the issues directory and its subdirectories exist."""
        if not self.issues_root.is_dir():
            if self.issues_root.exists() or self.issues_root.is_symlink():
                raise RuntimeError(
                    f"The tasks directory '{self.issues_root}' exists but is not a directory. "
                    "Please delete it or configure a different path."
                )
            self.issues_root.mkdir(parents=True, exist_ok=True)
        if not self.mission_dir.is_dir():
            if self.mission_dir.exists() or self.mission_dir.is_symlink():
                raise RuntimeError(
                    f"The mission directory '{self.mission_dir}' exists but is not a directory. "
                    "Please delete it or configure a different path."
                )
            self.mission_dir.mkdir(parents=True, exist_ok=True)
        for subdir in ["pending", "draft", "active", "completed", "mr"]:
            sub_path = self.issues_root / subdir
            if not sub_path.is_dir():
                if sub_path.exists() or sub_path.is_symlink():
                    raise RuntimeError(
                        f"The task subdirectory '{sub_path}' exists but is not a directory. "
                        "Please delete it or configure a different path."
                    )
                sub_path.mkdir(parents=True, exist_ok=True)

    def lock_mission_files(self):
        """Ensure mission.usv and datapackage.json are read-only."""
        if self.mission_path.exists():
            self._set_writable(self.mission_path, False)
        dp_path = self.mission_dir / "datapackage.json"
        if dp_path.exists():
            self._set_writable(dp_path, False)

    def _migrate_mission_files(self):
        """Migrate mission files from issues_root to .task-agent/ subdirectory."""
        old_mission = self.issues_root / "mission.usv"
        old_dp = self.issues_root / "datapackage.json"

        migrated = False
        if old_mission.exists() or old_dp.exists():
            self.mission_dir.mkdir(exist_ok=True)

            if old_mission.exists() and not self.mission_path.exists():
                shutil.move(str(old_mission), str(self.mission_path))
                migrated = True

            if old_dp.exists() and not (self.mission_dir / "datapackage.json").exists():
                shutil.move(str(old_dp), str(self.mission_dir / "datapackage.json"))
                migrated = True

            if migrated:
                print("Migrated mission files to .task-agent/ directory")

    def init_project(self) -> Tuple[int, int]:
        """Initialize or heal the task agent structure in the current project.
        Syncs disk state with mission.usv. Returns (num_new, num_removed)."""
        # Migrate mission files to .task-agent/ if needed
        self._migrate_mission_files()

        # Robust migration from issues/ to tasks/
        parent = self.issues_root.parent
        legacy_issues = parent / "issues"
        target_tasks = parent / "tasks"

        if legacy_issues.exists() or legacy_issues.is_symlink():
            if not target_tasks.exists() and not target_tasks.is_symlink():
                # Perform the move/rename
                if legacy_issues.is_symlink():
                    # Get target (could be relative or absolute)
                    link_target = os.readlink(str(legacy_issues))
                    target_path = legacy_issues.parent / link_target

                    # If the target folder name contains "-issues", rename it to "-tasks"
                    if "-issues" in target_path.name:
                        new_target_name = target_path.name.replace("-issues", "-tasks")
                        new_target_path = target_path.parent / new_target_name
                        if not new_target_path.exists():
                            target_path.rename(new_target_path)
                            # Update link_target for the new symlink
                            link_target = link_target.replace(
                                target_path.name, new_target_name
                            )

                    # Remove old symlink
                    legacy_issues.unlink()
                    # Create new symlink at docs/tasks
                    os.symlink(link_target, str(target_tasks))
                else:
                    # It's a directory
                    legacy_issues.rename(target_tasks)

                # Update self state if we were pointing to the legacy name
                if self.issues_root.name == "issues":
                    self.issues_root = target_tasks
                    self.mission_dir = self.issues_root / ".task-agent"
                    self.mission_path = self.mission_dir / "mission.usv"
                    # Refresh mission root too
                    self.mission_root = self._get_git_root(self.issues_root)
            else:
                # Merge if both exist
                if legacy_issues.is_dir() and target_tasks.is_dir():
                    for item in legacy_issues.iterdir():
                        dest = target_tasks / item.name
                        if not dest.exists():
                            shutil.move(str(item), str(dest))
                    # Remove legacy only if now empty
                    if not any(legacy_issues.iterdir()):
                        legacy_issues.rmdir()

        self.ensure_issues_dir()
        num_new, num_removed = self.ingest_issues()
        self.migrate_all_to_folders()
        self.save_datapackage()
        self.lock_mission_files()
        return num_new, num_removed

    @staticmethod
    def slugify(text: str) -> str:
        """Convert text to a slug. Converts underscores and spaces to hyphens."""
        text = text.lower()
        # Remove everything except alphanumeric, spaces, underscores, hyphens, and dots.
        text = re.sub(r"[^\w\s.-]", "", text)
        # Convert both spaces and underscores to hyphens
        text = re.sub(r"[\s_]+", "-", text)
        # Collapse multiple hyphens
        text = re.sub(r"[-]+", "-", text)
        return text.strip("-")

    def migrate_all_to_folders(self) -> int:
        """Migrate all file-based issues to folder format.
        Returns the count of migrated issues."""
        count = 0
        for status in ["pending", "draft", "active"]:
            status_dir = self.issues_root / status
            if not status_dir.exists():
                continue
            for md_file in status_dir.glob("*.md"):
                slug = self.slugify(md_file.stem)
                if self.migrate_to_folder(slug):
                    count += 1
        return count

    def find_issue_file(
        self, slug: str, include_completed: bool = False
    ) -> Optional[Path]:
        """Find the issue markdown file by slug.
        Checks for slug.md OR slug/README.md.
        Resilient to underscore/hyphen differences."""
        if not self.issues_root.exists():
            return None

        search_dirs = [d for d in self.issues_root.iterdir() if d.is_dir()]
        if not include_completed:
            search_dirs = [d for d in search_dirs if d.name != "completed"]
        else:
            # If including completed, we also need to search the year-based subdirectories
            completed_root = self.issues_root / "completed"
            if completed_root.exists():
                for year_dir in completed_root.iterdir():
                    if year_dir.is_dir():
                        search_dirs.append(year_dir)

        # Normalize target slug
        target_slug = self.slugify(slug)

        for directory in search_dirs:
            # 1. Exact match check (fast)
            issue_file = directory / f"{slug}.md"
            if issue_file.exists():
                return issue_file

            issue_dir_file = directory / slug / "README.md"
            if issue_dir_file.exists():
                return issue_dir_file

            # 2. Resilient check (slugify existing files)
            for f in directory.glob("*.md"):
                if self.slugify(f.stem) == target_slug:
                    return f

            for d in directory.iterdir():
                if d.is_dir():
                    readme = d / "README.md"
                    if readme.exists() and self.slugify(d.name) == target_slug:
                        return readme

        return None

    def migrate_to_folder(self, slug: str) -> Optional[Path]:
        """Migrate a file-based issue to folder-based format.
        Converts slug.md to slug/README.md.
        Returns the new README path if migration happened, None otherwise."""
        issue_file = self.find_issue_file(slug)
        if not issue_file:
            return None

        if issue_file.name == "README.md":
            return issue_file

        if not issue_file.exists():
            return None

        is_dir_based = issue_file.name == "README.md"
        if is_dir_based:
            return issue_file

        content = issue_file.read_text(encoding="utf-8")
        slug_dir = issue_file.parent / slug
        slug_dir.mkdir(parents=True, exist_ok=True)
        new_readme = slug_dir / "README.md"
        new_readme.write_text(content, encoding="utf-8")
        issue_file.unlink()
        return new_readme

    def restore_issue(self, slug: str, to_status: str = "pending") -> Issue:
        """Restore a completed issue back to a specified status."""
        if to_status not in ["pending", "draft", "active"]:
            raise ValueError(f"Invalid restoration status: {to_status}")

        issue_file = self.find_issue_file(slug, include_completed=True)
        if not issue_file:
            raise FileNotFoundError(f"Completed issue '{slug}' not found.")

        # Ensure it's actually in completed/
        if "completed" not in str(issue_file):
            # Already not completed, just move it if needed?
            # For now, if it's already in pending/draft/active, we just return it.
            # But the user asked specifically to 'restore from completed'.
            current_status = "unknown"
            for s in ["pending", "draft", "active"]:
                if s in str(issue_file):
                    current_status = s

            if current_status == to_status:
                issues = self.load_mission()
                for i in issues:
                    if i.slug == slug:
                        return i

        # Perform the move
        is_dir_based = issue_file.name == "README.md"
        source = issue_file.parent if is_dir_based else issue_file
        dest = self.issues_root / to_status / source.name

        shutil.move(str(source), str(dest))

        # Add back to mission USV
        issues = self.load_mission()
        # Remove if somehow already there (shouldn't be)
        issues = [i for i in issues if i.slug != slug]

        # Extract deps and name
        final_file = dest / "README.md" if is_dir_based else dest
        deps = self.extract_deps(final_file)
        name = self.extract_title(final_file)

        new_issue = Issue(
            name=name,
            slug=slug,
            status=to_status,
            priority=len(issues) + 1,
            dependencies=deps,
        )
        issues.append(new_issue)
        self.save_mission(issues)
        self.sync_mission()

        return new_issue

    def load_mission(self) -> List[Issue]:
        # Check new location first (.task-agent/mission.usv)
        if self.mission_path.exists():
            mission_file = self.mission_path
        # Check legacy location (mission.usv in issues_root) for migration
        elif (self.issues_root / "mission.usv").exists():
            mission_file = self.issues_root / "mission.usv"
        else:
            return []

        issues = []
        with mission_file.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(USV_DELIM)
                if len(parts) >= 1:
                    try:
                        blocked_by: List[str] = []
                        subtask_of: Optional[str] = None
                        if len(parts) == 1:
                            # Legacy format: slug only
                            slug = parts[0]
                            name = slug  # Fallback to slug
                        elif len(parts) == 2:
                            name = parts[0]
                            slug = parts[1]
                        elif len(parts) == 3:
                            name = parts[0]
                            slug = parts[1]
                            blocked_by = [
                                d.strip() for d in parts[2].split(",") if d.strip()
                            ]
                        else:
                            name = parts[0]
                            slug = parts[1]
                            blocked_by = [
                                d.strip() for d in parts[2].split(",") if d.strip()
                            ]
                            subtask_of = parts[3].strip() or None

                        # Determine status from file location
                        issue_file = self.find_issue_file(slug)
                        if issue_file:
                            # If it's slug/README.md, status is parent of parent
                            if issue_file.name == "README.md":
                                status = issue_file.parent.parent.name
                            else:
                                status = issue_file.parent.name
                        else:
                            # Fallback during migration or if file is temporarily gone
                            status = "unknown"

                        issues.append(
                            Issue(
                                name=name,
                                slug=slug,
                                blocked_by=blocked_by,
                                subtask_of=subtask_of,
                                priority=i,
                                status=status,
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        return issues

    def save_mission(self, issues: List[Issue]):
        """Save the list of issues back to mission.usv."""
        self.mission_dir.mkdir(parents=True, exist_ok=True)
        self._set_writable(self.mission_path, True)
        with self.mission_path.open("w", encoding="utf-8", newline="\n") as f:
            for issue in issues:
                f.write(issue.to_usv() + "\n")
        self._set_writable(self.mission_path, False)

    def save_datapackage(self):
        """Save the datapackage.json file."""
        datapackage = {
            "name": "mission-control",
            "resources": [
                {
                    "name": "mission",
                    "path": "mission.usv",
                    "format": "csv",
                    "delimiter": "\u001f",
                    "schema": {
                        "fields": [
                            {"name": "name", "type": "string"},
                            {"name": "slug", "type": "string"},
                            {"name": "blocked_by", "type": "string"},
                            {"name": "subtask_of", "type": "string"},
                        ]
                    },
                }
            ],
        }
        self.mission_dir.mkdir(parents=True, exist_ok=True)
        dp_path = self.mission_dir / "datapackage.json"
        self._set_writable(dp_path, True)
        with dp_path.open("w", encoding="utf-8") as f:
            json.dump(datapackage, f, indent=2)
        self._set_writable(dp_path, False)

    def sync_mission(self, ingest: bool = True) -> List[Issue]:
        """Load, sort by status groups, and save back."""
        if ingest:
            self.ingest_issues(sync=False)
        issues = self.load_mission()
        if not issues:
            return []

        # Sort: active -> pending -> draft -> unknown/others
        status_order = {"active": 0, "pending": 1, "draft": 2}
        sorted_issues = sorted(
            issues, key=lambda x: (status_order.get(x.status, 99), x.priority)
        )

        # Re-assign priority based on new order
        for i, issue in enumerate(sorted_issues, 1):
            issue.priority = i

        self.save_mission(sorted_issues)
        return sorted_issues

    def get_next_issue(self) -> Optional[Issue]:
        """Get the top prioritized issue."""
        issues = self.sync_mission()
        if not issues:
            return None
        return issues[0]

    @staticmethod
    def get_git_commit() -> str:
        """Get the short git commit hash."""
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
                text=True,
                shell=(os.name == "nt"),
            ).strip()
        except subprocess.CalledProcessError:
            return "unknown"

    @staticmethod
    def extract_relations(file_path: Path) -> Tuple[List[str], Optional[str]]:
        """Extract blocked_by and subtask_of from a markdown file."""
        blocked_by = []
        subtask_of = None
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()

                # Parse blocked by
                m_blocked = re.search(
                    r"\*\*Blocked by:\*\*[ \t]*(.*)", content, re.IGNORECASE
                )
                if m_blocked:
                    blocked_by = [
                        d.strip() for d in m_blocked.group(1).split(",") if d.strip()
                    ]

                # Parse subtask of
                m_subtask = re.search(
                    r"\*\*Subtask of:\*\*[ \t]*(.*)", content, re.IGNORECASE
                )
                if m_subtask:
                    subtask_of = m_subtask.group(1).strip() or None

                # Legacy depends on (alias for blocked_by)
                m_depends = re.search(
                    r"\*\*Depends on:\*\*[ \t]*(.*)", content, re.IGNORECASE
                )
                if m_depends:
                    legacy_deps = [
                        d.strip() for d in m_depends.group(1).split(",") if d.strip()
                    ]
                    if not blocked_by:
                        blocked_by = legacy_deps
        except Exception:
            pass
        return blocked_by, subtask_of

    @staticmethod
    def extract_deps(file_path: Path) -> List[str]:
        """Legacy helper. Returns combined dependencies for compatibility."""
        blocked_by, subtask_of = TaskAgent.extract_relations(file_path)
        deps = list(blocked_by)
        if subtask_of:
            deps.append(subtask_of)
        return deps

    @staticmethod
    def extract_title(file_path: Path) -> str:
        """Helper to extract the H1 title from a markdown file."""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("# "):
                        # Return the title without the '# ' prefix, and strip any leading/trailing whitespace
                        # Also handle the case where the user might have multiple #, like '# # My Title'
                        return line.lstrip("#").strip()
        except Exception:
            pass
        # Fallback to filename if no title found
        return file_path.stem

    def create_issue(
        self,
        title: str,
        body: str = "",
        draft: bool = False,
        depends_on: Optional[str] = None,
        as_dir: bool = False,
        completion_criteria: Optional[str] = None,
        blocked_by: Optional[str] = None,
        subtask_of: Optional[str] = None,
    ) -> Issue:
        """Create a new issue."""
        # Sanitize title for slug, but keep original for 'name'
        # If title starts with '# ', strip it for both
        display_name = title.lstrip("#").strip()
        slug = self.slugify(display_name)
        status = "draft" if draft else "pending"
        target_dir = self.issues_root / status
        target_dir.mkdir(parents=True, exist_ok=True)

        if as_dir:
            issue_container = target_dir / slug
            issue_container.mkdir(parents=True, exist_ok=True)
            issue_file = issue_container / "README.md"
        else:
            issue_file = target_dir / f"{slug}.md"

        if issue_file.exists():
            raise FileExistsError(f"Issue file already exists: {issue_file}")

        # Resolve relations
        blocked_by_list = []
        if blocked_by:
            blocked_by_list = [d.strip() for d in blocked_by.split(",") if d.strip()]
        elif depends_on:
            blocked_by_list = [d.strip() for d in depends_on.split(",") if d.strip()]

        # Write the markdown file
        created_at = datetime.now().astimezone().isoformat()
        with issue_file.open("w", encoding="utf-8") as f:
            f.write(f"---\ncreated_at: {created_at}\n---\n\n")
            f.write(f"# {display_name}\n\n")
            if subtask_of:
                f.write(f"**Subtask of:** {subtask_of.strip()}\n\n")
            if blocked_by_list:
                f.write(f"**Blocked by:** {', '.join(blocked_by_list)}\n\n")
            f.write(f"{body}\n")
            if completion_criteria:
                f.write(f"\n## Completion Criteria\n\n{completion_criteria}\n")

        # Update mission.usv and datapackage.json via init
        self.init_project()
        # Reload to get the issue with proper priority from mission.usv
        issues = self.load_mission()
        return next(i for i in issues if i.slug == slug)

    def promote_issue(self, slug: str) -> Issue:
        """Promote an issue from draft to pending. Also promotes any draft children."""
        issues = self.load_mission()
        target = next(
            (i for i in issues if i.slug == slug and i.status == "draft"), None
        )
        if not target:
            raise ValueError(f"Draft issue '{slug}' not found.")

        promoted = [target.slug]

        def promote_single(s: str):
            self.migrate_to_folder(s)
            issue_file = self.find_issue_file(s)
            if not issue_file:
                return
            is_dir_based = issue_file.name == "README.md"
            source = issue_file.parent if is_dir_based else issue_file
            dest = self.issues_root / "pending" / source.name
            shutil.move(str(source), str(dest))

        promote_single(target.slug)

        children = [
            i.slug
            for i in issues
            if (i.subtask_of == target.slug or target.slug in i.blocked_by)
            and i.status == "draft"
        ]
        for child_slug in children:
            promote_single(child_slug)
            promoted.append(child_slug)

        self.sync_mission()
        target.status = "pending"
        return target

    def demote_issue(self, slug: str) -> Issue:
        """Demote an issue: active -> pending -> draft. Also cascades children."""
        issues = self.load_mission()
        target = next(
            (i for i in issues if i.slug == slug and i.status in ("pending", "active")),
            None,
        )
        if not target:
            raise ValueError(f"Pending or active issue '{slug}' not found.")

        to_status = "pending" if target.status == "active" else "draft"

        def demote_single(s: str):
            self.migrate_to_folder(s)
            issue_file = self.find_issue_file(s)
            if not issue_file:
                return
            is_dir_based = issue_file.name == "README.md"
            source = issue_file.parent if is_dir_based else issue_file
            dest = self.issues_root / to_status / source.name
            shutil.move(str(source), str(dest))

        demote_single(target.slug)

        children = [
            i.slug
            for i in issues
            if (i.subtask_of == target.slug or target.slug in i.blocked_by)
            and i.status == target.status
        ]
        for child_slug in children:
            demote_single(child_slug)

        self.sync_mission()
        target.status = to_status
        return target

    def move_to_active(self, slug: str) -> Issue:
        """Move an issue to active status."""
        issues = self.load_mission()
        target = next((i for i in issues if i.slug == slug), None)
        if not target:
            raise ValueError(f"Issue '{slug}' not found.")

        if target.status == "active":
            return target

        if target.status not in ["pending", "draft"]:
            raise ValueError(
                f"Issue '{slug}' cannot be marked as active from status '{target.status}'."
            )

        self.migrate_to_folder(target.slug)
        issue_file = self.find_issue_file(target.slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for '{target.slug}'.")

        is_dir_based = issue_file.name == "README.md"
        source = issue_file.parent if is_dir_based else issue_file
        dest = self.issues_root / "active" / source.name

        shutil.move(str(source), str(dest))
        self.sync_mission()
        target.status = "active"
        return target

    def add_dependency(self, slug: str, depends_on: str) -> None:
        """Add a dependency (blocked_by) to an issue."""
        issue_file = self.find_issue_file(slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for '{slug}'.")

        content = issue_file.read_text(encoding="utf-8")
        blocked_by, subtask_of = self.extract_relations(issue_file)

        if depends_on in blocked_by:
            return

        blocked_by.append(depends_on)

        # Update Markdown
        pattern_blocked = r"\*\*Blocked by:\*\*[ \t]*(.*)"
        pattern_depends = r"\*\*Depends on:\*\*[ \t]*(.*)"

        has_blocked = re.search(pattern_blocked, content)
        has_depends = re.search(pattern_depends, content)

        new_line = f"**Blocked by:** {', '.join(blocked_by)}"

        if has_blocked:
            content = re.sub(pattern_blocked, new_line, content)
        elif has_depends:
            content = re.sub(pattern_depends, new_line, content)
        else:
            # Insert it right after H1
            lines = content.splitlines()
            inserted = False
            for idx, line in enumerate(lines):
                if line.strip().startswith("# "):
                    lines.insert(idx + 1, "")
                    lines.insert(idx + 2, new_line)
                    inserted = True
                    break
            if inserted:
                content = "\n".join(lines) + "\n"
            else:
                content = new_line + "\n\n" + content

        self._set_writable(issue_file, True)
        issue_file.write_text(content, encoding="utf-8")

        issues = self.load_mission()
        for issue in issues:
            if issue.slug == slug:
                issue.blocked_by = blocked_by
                break
        self.save_mission(issues)

    def remove_dependency(self, slug: str, depends_on: str) -> None:
        """Remove a dependency (blocked_by) from an issue."""
        issue_file = self.find_issue_file(slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for '{slug}'.")

        content = issue_file.read_text(encoding="utf-8")
        blocked_by, subtask_of = self.extract_relations(issue_file)

        if depends_on not in blocked_by:
            return

        blocked_by.remove(depends_on)

        pattern_blocked = r"\*\*Blocked by:\*\*[ \t]*(.*)"
        pattern_depends = r"\*\*Depends on:\*\*[ \t]*(.*)"

        has_blocked = re.search(pattern_blocked, content)

        pattern = pattern_blocked if has_blocked else pattern_depends

        if blocked_by:
            new_line = f"**Blocked by:** {', '.join(blocked_by)}"
            content = re.sub(pattern, new_line, content)
        else:
            content = re.sub(pattern + r"\n*", "", content)

        self._set_writable(issue_file, True)
        issue_file.write_text(content, encoding="utf-8")

        issues = self.load_mission()
        for issue in issues:
            if issue.slug == slug:
                issue.blocked_by = blocked_by
                break
        self.save_mission(issues)

    def _git_commit(
        self,
        repo_root: Path,
        message: str,
        amend: bool = False,
        files: Optional[List[str]] = None,
        no_verify: bool = True,
    ) -> str:
        """Helper to perform a git commit with retry logic for hooks."""

        def _get_git_add_path(f: str) -> str:
            resolved_f = Path(f).resolve()
            try:
                rel_f = resolved_f.relative_to(repo_root.resolve())
                return str(rel_f)
            except ValueError:
                return f

        if files:
            for f in files:
                git_add_path = _get_git_add_path(f)
                subprocess.run(
                    ["git", "-C", str(repo_root), "add", git_add_path],
                    check=False,
                    shell=(os.name == "nt"),
                )
        else:
            subprocess.run(
                ["git", "-C", str(repo_root), "add", "."],
                check=False,
                shell=(os.name == "nt"),
            )

        cmd = ["git", "-C", str(repo_root), "commit", "-m", message]
        if no_verify:
            cmd.append("--no-verify")
        if amend:
            cmd = ["git", "-C", str(repo_root), "commit", "--amend", "--no-edit"]
            if no_verify:
                cmd.append("--no-verify")

        res = subprocess.run(
            cmd, capture_output=True, text=True, shell=(os.name == "nt")
        )
        if res.returncode != 0:
            combined = (res.stdout or "") + (res.stderr or "")
            if (
                "nothing to commit" in combined
                or "nothing added to commit" in combined
                or "working tree clean" in combined
                or "no changes added to commit" in combined
            ):
                return "no_changes"

            if not amend:
                # Retry once for pre-commit hooks
                if files:
                    for f in files:
                        git_add_path = _get_git_add_path(f)
                        subprocess.run(
                            ["git", "-C", str(repo_root), "add", git_add_path],
                            check=False,
                            shell=(os.name == "nt"),
                        )
                else:
                    subprocess.run(
                        ["git", "-C", str(repo_root), "add", "."],
                        check=False,
                        shell=(os.name == "nt"),
                    )
                res = subprocess.run(
                    cmd, capture_output=True, text=True, shell=(os.name == "nt")
                )

        if res.returncode == 0:
            try:
                return subprocess.check_output(
                    ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    shell=(os.name == "nt"),
                ).strip()
            except Exception:
                return "unknown"

        combined = (res.stdout or "") + (res.stderr or "")
        if (
            "nothing to commit" in combined
            or "nothing added to commit" in combined
            or "working tree clean" in combined
            or "no changes added to commit" in combined
        ):
            return "no_changes"

        return "failed"

    def _git_push(self, repo_root: Path) -> bool:
        """Push a repository using native git."""
        try:
            subprocess.run(
                ["git", "-C", str(repo_root), "push"],
                check=True,
                capture_output=True,
                text=True,
                shell=(os.name == "nt"),
            )
            return True
        except subprocess.CalledProcessError:
            return False

    def complete_issue(
        self,
        slug: str,
        commit_message: Optional[str] = None,
        should_commit: bool = True,
        push_mission: bool = False,
        solution_explanation: Optional[str] = None,
        no_verify: bool = True,
    ) -> Tuple[Issue, str]:
        """Mark an issue as done. Returns (issue, commit_hash)."""
        issues = self.load_mission()
        target_issue = next((i for i in issues if i.slug == slug), None)
        if not target_issue:
            raise ValueError(f"Issue '{slug}' not found.")

        # Check for open subtasks
        open_subtasks = [
            i for i in issues if i.subtask_of == slug and i.status != "completed"
        ]
        if open_subtasks:
            subtask_slugs = ", ".join(i.slug for i in open_subtasks)
            raise ValueError(
                f"Cannot complete task '{slug}' because it has open sub-tasks: {subtask_slugs}"
            )

        self.migrate_to_folder(target_issue.slug)
        issue_file = self.find_issue_file(target_issue.slug)
        if not issue_file:
            raise FileNotFoundError(
                f"Issue file not found for slug: {target_issue.slug}"
            )

        # 1. Prepare Move
        is_dir_based = issue_file.name == "README.md"
        source_to_move = issue_file.parent if is_dir_based else issue_file

        year = datetime.now().year
        completed_dir = self.issues_root / "completed" / str(year)
        completed_dir.mkdir(parents=True, exist_ok=True)

        dest_path = completed_dir / source_to_move.name

        # 2. Add placeholder to content
        with issue_file.open("r", encoding="utf-8") as f:
            content = f.read()

        if not content.endswith("\n"):
            content += "\n"

        if solution_explanation:
            content += f"\n## Solution\n\n{solution_explanation}\n"

        content += "\n---\n**Completed in commit:** `<pending-commit-id>`\n"

        # 3. Execute Move and USV update (Mission Repo)
        if is_dir_based:
            if dest_path.exists():
                shutil.rmtree(dest_path)
            shutil.move(str(source_to_move), str(dest_path))
            with (dest_path / "README.md").open("w", encoding="utf-8") as f:
                f.write(content)
            final_file = dest_path / "README.md"
        else:
            with dest_path.open("w", encoding="utf-8") as f:
                f.write(content)
            issue_file.unlink()
            final_file = dest_path

        new_issues = [i for i in issues if i.slug != target_issue.slug]
        self.save_mission(new_issues)

        # 4. Commit Logic
        code_hash = "unknown"
        committed = False
        if should_commit:
            msg = commit_message or f"feat: complete {target_issue.slug}"

            # A. Commit Code Changes (Main Repo)
            if self.code_root:
                code_hash = self._git_commit(self.code_root, msg, no_verify=no_verify)
                if code_hash == "failed":
                    raise RuntimeError("Failed to commit changes to code repository.")
                if code_hash == "no_changes":
                    code_hash = self.get_git_commit()
                else:
                    committed = True

            # B. Commit Mission Changes (Mission Repo)
            # If they are different, we perform a second commit
            if self.is_dual_repo and self.mission_root:
                mission_msg = f"task: finalize {target_issue.slug}"
                mission_hash = self._git_commit(
                    self.mission_root, mission_msg, no_verify=no_verify
                )
                if mission_hash == "failed":
                    raise RuntimeError(
                        "Failed to commit changes to mission repository."
                    )
                if mission_hash != "no_changes":
                    committed = True

        # 5. Update issue file with the code hash
        # If we didn't commit, we use the current HEAD or 'pending'
        if code_hash == "unknown":
            code_hash = self.get_git_commit()

        file_text = final_file.read_text(encoding="utf-8")
        file_text = file_text.replace("<pending-commit-id>", code_hash)
        final_file.write_text(file_text, encoding="utf-8")

        # 6. Amend the mission commit if in dual mode, or the code commit if single mode
        if committed:
            if self.is_dual_repo and self.mission_root:
                res = self._git_commit(
                    self.mission_root, "", amend=True, files=[str(final_file)]
                )
                if res == "failed":
                    raise RuntimeError("Failed to amend mission commit.")
            elif self.code_root:
                res = self._git_commit(
                    self.code_root, "", amend=True, files=[str(final_file)]
                )
                if res == "failed":
                    raise RuntimeError("Failed to amend code commit.")

        # 7. Optional Push
        if push_mission and self.mission_root:
            self.push_mission_repo()

        target_issue.status = "completed"
        return target_issue, code_hash

    def soft_delete_issue(self, slug: str) -> Issue:
        """Soft-delete an issue: move to deleted/ folder and remove from mission.usv.

        Does NOT create a git commit — the task is archived for later reassessment.
        """
        issues = self.load_mission()
        target = next((i for i in issues if i.slug == slug), None)
        if not target:
            raise ValueError(f"Issue '{slug}' not found.")

        self.migrate_to_folder(target.slug)
        issue_file = self.find_issue_file(target.slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for slug: {target.slug}")

        # 1. Create deleted/ directory
        deleted_dir = self.issues_root / "deleted"
        deleted_dir.mkdir(parents=True, exist_ok=True)

        # 2. Move the task file/folder
        is_dir_based = issue_file.name == "README.md"
        source_to_move = issue_file.parent if is_dir_based else issue_file
        dest_path = deleted_dir / source_to_move.name
        if dest_path.exists():
            shutil.rmtree(str(dest_path)) if dest_path.is_dir() else dest_path.unlink()
        shutil.move(str(source_to_move), str(dest_path))

        # 3. Append to deleted.usv with timestamp and original status
        deleted_usv = deleted_dir / "deleted.usv"
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        deps_str = ",".join(target.dependencies)
        line = f"{target.name}\x1f{target.slug}\x1f{deps_str}\x1f{target.status}\x1f{timestamp}\n"
        with deleted_usv.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line)

        # 4. Remove from mission.usv
        new_issues = [i for i in issues if i.slug != slug]
        self.save_mission(new_issues)

        target.status = "deleted"
        return target

    def prioritize_issue(self, slug: str, direction: str) -> Issue:
        """Move an issue up or down in priority."""
        issues = self.load_mission()

        idx = -1
        for i, issue in enumerate(issues):
            if issue.slug == slug:
                idx = i
                break

        if idx == -1:
            raise ValueError(f"Issue '{slug}' not found in mission.")

        if direction == "up":
            if idx > 0:
                issues[idx], issues[idx - 1] = issues[idx - 1], issues[idx]
        elif direction == "down":
            if idx < len(issues) - 1:
                issues[idx], issues[idx + 1] = issues[idx + 1], issues[idx]
        else:
            raise ValueError("Direction must be 'up' or 'down'.")

        self.save_mission(issues)
        self.sync_mission()
        return issues[idx]

    def update_issue(self, slug: str, content: str) -> Issue:
        """Update the content of an issue."""
        issue_file = self.find_issue_file(slug, include_completed=True)
        if not issue_file:
            raise FileNotFoundError(f"Issue '{slug}' not found.")

        # Extract temporary relations from new content to validate them
        blocked_by = []
        subtask_of = None

        m_blocked = re.search(r"\*\*Blocked by:\*\*[ \t]*(.*)", content, re.IGNORECASE)
        if m_blocked:
            blocked_by = [d.strip() for d in m_blocked.group(1).split(",") if d.strip()]

        m_subtask = re.search(r"\*\*Subtask of:\*\*[ \t]*(.*)", content, re.IGNORECASE)
        if m_subtask:
            subtask_of = m_subtask.group(1).strip() or None

        m_depends = re.search(r"\*\*Depends on:\*\*[ \t]*(.*)", content, re.IGNORECASE)
        if m_depends and not blocked_by:
            blocked_by = [d.strip() for d in m_depends.group(1).split(",") if d.strip()]

        if slug in blocked_by:
            raise ValueError("A task cannot depend on itself.")
        if slug == subtask_of:
            raise ValueError("A task cannot be a subtask of itself.")

        issues = self.load_mission()
        existing_slugs = {i.slug for i in issues}
        for dep in blocked_by:
            if dep not in existing_slugs:
                raise ValueError(f"Prerequisite task '{dep}' does not exist.")
        if subtask_of and subtask_of not in existing_slugs:
            raise ValueError(f"Parent task '{subtask_of}' does not exist.")

        combined_new_deps = list(blocked_by)
        if subtask_of:
            combined_new_deps.append(subtask_of)

        if self._check_dependency_cycle(issues, slug, combined_new_deps):
            raise ValueError("Adding these relationships would introduce a cycle.")

        issue_file.write_text(content, encoding="utf-8")

        # Re-extract name and deps in case they changed
        updated = False
        for i in issues:
            if i.slug == slug:
                i.name = self.extract_title(issue_file)
                i.blocked_by = blocked_by
                i.subtask_of = subtask_of
                updated = True
                break

        if updated:
            self.save_mission(issues)

        # Return the issue object
        for i in issues:
            if i.slug == slug:
                return i

        # If it was completed, it's not in mission.usv
        return Issue(
            name=self.extract_title(issue_file),
            slug=slug,
            dependencies=self.extract_deps(issue_file),
            status="completed",
        )

    def update_dependencies(self, slug: str, depends_on: str) -> Issue:
        """Update dependencies (blocked_by) of an issue."""
        issue_file = self.find_issue_file(slug, include_completed=True)
        if not issue_file:
            raise FileNotFoundError(f"Issue '{slug}' not found.")

        # Parse new dependencies
        new_deps = [d.strip() for d in depends_on.split(",") if d.strip()]

        if slug in new_deps:
            raise ValueError("A task cannot depend on itself.")

        issues = self.load_mission()
        existing_slugs = {i.slug for i in issues}
        for dep in new_deps:
            if dep not in existing_slugs:
                raise ValueError(f"Prerequisite task '{dep}' does not exist.")

        # Check for cycles
        if self._check_dependency_cycle(issues, slug, new_deps):
            raise ValueError("Adding these dependencies would introduce a cycle.")

        # Update Markdown content
        content = issue_file.read_text(encoding="utf-8")

        # Replace either **Blocked by:** or **Depends on:**
        pattern_blocked = r"\*\*Blocked by:\*\*[ \t]*(.*)"
        pattern_depends = r"\*\*Depends on:\*\*[ \t]*(.*)"

        has_blocked = re.search(pattern_blocked, content)
        has_depends = re.search(pattern_depends, content)

        if has_blocked or has_depends:
            pattern = pattern_blocked if has_blocked else pattern_depends
            if new_deps:
                content = re.sub(
                    pattern,
                    f"**Blocked by:** {', '.join(new_deps)}",
                    content,
                )
            else:
                # Remove the line and any trailing blank lines
                content = re.sub(pattern + r"\n*", "", content)
        else:
            if new_deps:
                # Insert it right after the H1 title
                lines = content.splitlines()
                inserted = False
                for idx, line in enumerate(lines):
                    if line.strip().startswith("# "):
                        lines.insert(idx + 1, "")
                        lines.insert(idx + 2, f"**Blocked by:** {', '.join(new_deps)}")
                        inserted = True
                        break
                if inserted:
                    content = "\n".join(lines) + "\n"
                else:
                    content = f"**Blocked by:** {', '.join(new_deps)}\n\n" + content

        issue_file.write_text(content, encoding="utf-8")

        # Sync and reload
        updated = False
        for i in issues:
            if i.slug == slug:
                i.blocked_by = new_deps
                updated = True
                break

        if updated:
            self.save_mission(issues)

        # Return the updated issue object
        for i in issues:
            if i.slug == slug:
                return i

        return Issue(
            name=self.extract_title(issue_file),
            slug=slug,
            blocked_by=new_deps,
            status="completed",
        )

    def update_subtask_of(self, slug: str, subtask_of: Optional[str]) -> Issue:
        """Update the subtask_of parent relation of an issue."""
        issue_file = self.find_issue_file(slug, include_completed=True)
        if not issue_file:
            raise FileNotFoundError(f"Issue '{slug}' not found.")

        if subtask_of == slug:
            raise ValueError("A task cannot be a subtask of itself.")

        issues = self.load_mission()
        existing_slugs = {i.slug for i in issues}
        if subtask_of and subtask_of not in existing_slugs:
            raise ValueError(f"Parent task '{subtask_of}' does not exist.")

        # Check for cycles
        if subtask_of and self._check_dependency_cycle(issues, slug, [subtask_of]):
            raise ValueError("Setting this parent would introduce a cycle.")

        # Update Markdown content
        content = issue_file.read_text(encoding="utf-8")

        pattern_subtask = r"\*\*Subtask of:\*\*[ \t]*(.*)"
        has_subtask = re.search(pattern_subtask, content)

        if has_subtask:
            if subtask_of:
                content = re.sub(
                    pattern_subtask,
                    f"**Subtask of:** {subtask_of}",
                    content,
                )
            else:
                # Remove the line and any trailing blank lines
                content = re.sub(pattern_subtask + r"\n*", "", content)
        else:
            if subtask_of:
                # Insert it right after the H1 title
                lines = content.splitlines()
                inserted = False
                for idx, line in enumerate(lines):
                    if line.strip().startswith("# "):
                        lines.insert(idx + 1, "")
                        lines.insert(idx + 2, f"**Subtask of:** {subtask_of}")
                        inserted = True
                        break
                if inserted:
                    content = "\n".join(lines) + "\n"
                else:
                    content = f"**Subtask of:** {subtask_of}\n\n" + content

        issue_file.write_text(content, encoding="utf-8")

        # Sync and reload
        updated = False
        for i in issues:
            if i.slug == slug:
                i.subtask_of = subtask_of
                updated = True
                break

        if updated:
            self.save_mission(issues)

        # Return the updated issue object
        for i in issues:
            if i.slug == slug:
                return i

        return Issue(
            name=self.extract_title(issue_file),
            slug=slug,
            subtask_of=subtask_of,
            status="completed",
        )

    def ingest_issues(self, sync: bool = True) -> Tuple[int, int]:
        """Ingest existing markdown files. Returns (num_new, num_removed)."""
        self.ensure_issues_dir()

        existing_issues = self.load_mission()
        existing_slugs = {i.slug for i in existing_issues}
        present_issues = [i for i in existing_issues if i.status != "unknown"]

        def _ensure_created_at(file_path: Path):
            try:
                content = file_path.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = parts[1]
                        has_created_at = False
                        for line in frontmatter.splitlines():
                            if line.strip().startswith("created_at:"):
                                has_created_at = True
                                break
                        if not has_created_at:
                            created_at = datetime.now().astimezone().isoformat()
                            new_frontmatter = (
                                frontmatter.rstrip("\n")
                                + f"\ncreated_at: {created_at}\n"
                            )
                            new_content = f"---{new_frontmatter}---{parts[2]}"
                            file_path.write_text(new_content, encoding="utf-8")
                else:
                    created_at = datetime.now().astimezone().isoformat()
                    new_content = f"---\ncreated_at: {created_at}\n---\n\n" + content
                    file_path.write_text(new_content, encoding="utf-8")
            except Exception:
                pass

        def _migrate_file_headers(file_path: Path):
            try:
                content = file_path.read_text(encoding="utf-8")
                pattern_depends = r"\*\*Depends on:\*\*[ \t]*(.*)"
                if re.search(pattern_depends, content, re.IGNORECASE):
                    content = re.sub(
                        pattern_depends,
                        lambda m: f"**Blocked by:** {m.group(1)}",
                        content,
                        flags=re.IGNORECASE,
                    )
                    self._set_writable(file_path, True)
                    file_path.write_text(content, encoding="utf-8")
            except Exception:
                pass

        new_issues = []
        for status in ["pending", "draft", "active"]:
            status_dir = self.issues_root / status
            if not status_dir.exists():
                continue

            # File-based
            for issue_file in list(status_dir.glob("*.md")):
                _migrate_file_headers(issue_file)
                name = self.extract_title(issue_file)
                slug = self.slugify(issue_file.stem)
                if slug not in existing_slugs:
                    blocked_by, subtask_of = self.extract_relations(issue_file)
                    new_issues.append(
                        Issue(
                            name=name,
                            slug=slug,
                            blocked_by=blocked_by,
                            subtask_of=subtask_of,
                            status=status,
                        )
                    )
                    existing_slugs.add(slug)
                else:
                    for issue in present_issues:
                        if issue.slug == slug:
                            blocked_by, subtask_of = self.extract_relations(issue_file)
                            issue.name = name
                            issue.blocked_by = blocked_by
                            issue.subtask_of = subtask_of
                            issue.status = status
                            break
                _ensure_created_at(issue_file)

            # Directory-based
            for readme_file in list(status_dir.glob("*/README.md")):
                _migrate_file_headers(readme_file)
                name = self.extract_title(readme_file)
                slug = self.slugify(readme_file.parent.name)
                if slug not in existing_slugs:
                    blocked_by, subtask_of = self.extract_relations(readme_file)
                    new_issues.append(
                        Issue(
                            name=name,
                            slug=slug,
                            blocked_by=blocked_by,
                            subtask_of=subtask_of,
                            status=status,
                        )
                    )
                    existing_slugs.add(slug)
                else:
                    for issue in present_issues:
                        if issue.slug == slug:
                            blocked_by, subtask_of = self.extract_relations(readme_file)
                            issue.name = name
                            issue.blocked_by = blocked_by
                            issue.subtask_of = subtask_of
                            issue.status = status
                            break
                _ensure_created_at(readme_file)

        final_issues = present_issues + new_issues
        self.save_mission(final_issues)
        if sync:
            self.sync_mission(ingest=False)

        return len(new_issues), len(existing_issues) - len(present_issues)

    # ── Strategy ─────────────────────────────────────────────────────

    @property
    def strategy_dir(self) -> Path:
        """Path to the strategy directory."""
        return self.issues_root / "strategy"

    @property
    def strategy_file(self) -> Path:
        """Path to the strategy README."""
        return self.strategy_dir / "README.md"

    @property
    def strategy_meta_file(self) -> Path:
        """Path to the strategy metadata file."""
        return self.strategy_dir / ".meta.json"

    def get_strategy(self) -> Optional[str]:
        """Read the strategy content. Returns None if no strategy file exists."""
        if not self.strategy_file.exists():
            return None
        try:
            content = self.strategy_file.read_text(encoding="utf-8").strip()
            return content if content else None
        except Exception:
            return None

    def get_strategy_meta(self) -> dict:
        """Read strategy metadata (last_shown_at, cooldown_hours)."""
        if not self.strategy_meta_file.exists():
            return {}
        try:
            with self.strategy_meta_file.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def update_strategy_last_shown(self) -> None:
        """Update the timestamp of when the strategy was last displayed."""
        self.strategy_dir.mkdir(parents=True, exist_ok=True)
        meta = self.get_strategy_meta()
        meta["last_shown_at"] = datetime.now().isoformat()
        with self.strategy_meta_file.open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def should_show_strategy(self, cooldown_hours: float = 2.0) -> bool:
        """Check if enough time has elapsed to display the strategy again.

        Returns True if:
        - A strategy file exists with content, AND
        - The strategy has never been shown, OR
        - At least `cooldown_hours` have passed since last shown.
        """
        content = self.get_strategy()
        if not content:
            return False

        meta = self.get_strategy_meta()
        last_shown = meta.get("last_shown_at")
        if not last_shown:
            return True

        try:
            last_dt = datetime.fromisoformat(last_shown)
            elapsed = (datetime.now() - last_dt).total_seconds()
            return elapsed >= cooldown_hours * 3600
        except (ValueError, TypeError):
            return True

    def init_strategy(self) -> Path:
        """Create the strategy directory and a starter README if it doesn't exist."""
        self.strategy_dir.mkdir(parents=True, exist_ok=True)
        if not self.strategy_file.exists():
            self.strategy_file.write_text(
                "# Strategy\n\n"
                "_Define the current strategic direction for this project._\n\n"
                "<!-- Keep this concise — it will be displayed periodically in CLI output. -->\n",
                encoding="utf-8",
            )
        return self.strategy_file
