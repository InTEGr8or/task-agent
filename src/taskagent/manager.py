from typing import List, Optional, Tuple
from pathlib import Path
from datetime import datetime
import re
import subprocess
import os
import shutil

from taskagent.models.issue import Issue, USV_DELIM


class TaskAgent:
    def __init__(self, config_dir: Optional[str] = None):
        self.issues_root, self.mission_path = self.get_config_paths(config_dir)
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
            )
            return Path(res.stdout.strip())
        except subprocess.CalledProcessError:
            return None

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
        subprocess.run(["git", "-C", str(self.mission_root), "push"], check=True)

    @staticmethod
    def get_config_paths(config_dir: Optional[str] = None) -> Tuple[Path, Path]:
        """Get the issues root and mission path based on config or environment."""
        if config_dir:
            issues_root = Path(config_dir)
        else:
            # Check environment variable, then default to docs/issues
            env_dir = os.environ.get("TA_CONFIG_DIR")
            issues_root = Path(env_dir) if env_dir else Path("docs/issues")

        mission_path = issues_root / "mission.usv"
        return issues_root, mission_path

    def ensure_issues_dir(self):
        """Ensure the issues directory and its subdirectories exist."""
        for subdir in ["pending", "draft", "active", "completed"]:
            (self.issues_root / subdir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def slugify(text: str) -> str:
        """Convert text to a slug. Converts underscores and spaces to hyphens."""
        text = text.lower()
        # Remove everything except alphanumeric, spaces, underscores, and hyphens.
        text = re.sub(r"[^\w\s-]", "", text)
        # Convert both spaces and underscores to hyphens
        text = re.sub(r"[\s_]+", "-", text)
        # Collapse multiple hyphens
        text = re.sub(r"[-]+", "-", text)
        return text.strip("-")

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

        # Extract deps
        final_file = dest / "README.md" if is_dir_based else dest
        deps = self.extract_deps(final_file)

        new_issue = Issue(
            slug=slug, status=to_status, priority=len(issues) + 1, dependencies=deps
        )
        issues.append(new_issue)
        self.save_mission(issues)
        self.sync_mission()

        return new_issue

    def load_mission(self) -> List[Issue]:
        if not self.mission_path.exists():
            return []

        issues = []
        with self.mission_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split(USV_DELIM)
                if len(parts) >= 1:
                    try:
                        slug = parts[0]
                        deps = []
                        if len(parts) >= 2 and parts[1]:
                            deps = [d.strip() for d in parts[1].split(",") if d.strip()]

                        # Determine status from file location
                        issue_file = self.find_issue_file(slug)
                        status = "unknown"
                        if issue_file:
                            # If it's slug/README.md, status is parent of parent
                            if issue_file.name == "README.md":
                                status = issue_file.parent.parent.name
                            else:
                                status = issue_file.parent.name

                        issues.append(
                            Issue(
                                slug=slug, dependencies=deps, priority=i, status=status
                            )
                        )
                    except (ValueError, IndexError):
                        continue
        return issues

    def save_mission(self, issues: List[Issue]):
        """Save the list of issues back to mission.usv."""
        self.mission_path.parent.mkdir(parents=True, exist_ok=True)
        with self.mission_path.open("w", encoding="utf-8", newline="\n") as f:
            for issue in issues:
                f.write(issue.to_usv() + "\n")

    def sync_mission(self) -> List[Issue]:
        """Load, sort by status groups, and save back."""
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
            ).strip()
        except subprocess.CalledProcessError:
            return "unknown"

    @staticmethod
    def extract_deps(file_path: Path) -> List[str]:
        """Helper to extract dependencies from a markdown file."""
        try:
            with file_path.open("r", encoding="utf-8") as f:
                content = f.read()
                match = re.search(r"\*\*Depends on:\*\*\s*(.*)", content)
                if match:
                    return [d.strip() for d in match.group(1).split(",") if d.strip()]
        except Exception:
            pass
        return []

    def create_issue(
        self,
        title: str,
        body: str = "",
        draft: bool = False,
        depends_on: Optional[str] = None,
        as_dir: bool = False,
        completion_criteria: Optional[str] = None,
    ) -> Issue:
        """Create a new issue."""
        slug = self.slugify(title)
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

        deps = []
        if depends_on:
            deps = [d.strip() for d in depends_on.split(",") if d.strip()]

        # Write the markdown file
        with issue_file.open("w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n")
            if deps:
                f.write(f"**Depends on:** {', '.join(deps)}\n\n")
            f.write(f"{body}\n")
            if completion_criteria:
                f.write(f"\n## Completion Criteria\n\n{completion_criteria}\n")

        # Update mission.usv
        issues = self.load_mission()
        new_issue = Issue(
            slug=slug, dependencies=deps, status=status, priority=len(issues) + 1
        )
        issues.append(new_issue)
        self.save_mission(issues)
        return new_issue

    def promote_issue(self, slug: str) -> Issue:
        """Promote an issue from draft to pending."""
        issues = self.load_mission()
        target = next(
            (i for i in issues if i.slug == slug and i.status == "draft"), None
        )
        if not target:
            raise ValueError(f"Draft issue '{slug}' not found.")

        issue_file = self.find_issue_file(target.slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for '{target.slug}'.")

        is_dir_based = issue_file.name == "README.md"
        source = issue_file.parent if is_dir_based else issue_file
        dest = self.issues_root / "pending" / source.name

        shutil.move(str(source), str(dest))
        self.sync_mission()
        target.status = "pending"
        return target

    def demote_issue(self, slug: str) -> Issue:
        """Demote an issue from pending to draft."""
        issues = self.load_mission()
        target = next(
            (i for i in issues if i.slug == slug and i.status == "pending"), None
        )
        if not target:
            raise ValueError(f"Pending issue '{slug}' not found.")

        issue_file = self.find_issue_file(target.slug)
        if not issue_file:
            raise FileNotFoundError(f"Issue file not found for '{target.slug}'.")

        is_dir_based = issue_file.name == "README.md"
        source = issue_file.parent if is_dir_based else issue_file
        dest = self.issues_root / "draft" / source.name

        shutil.move(str(source), str(dest))
        self.sync_mission()
        target.status = "draft"
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

    def _git_commit(
        self,
        repo_root: Path,
        message: str,
        amend: bool = False,
        files: Optional[List[str]] = None,
    ) -> str:
        """Helper to perform a git commit with retry logic for hooks."""
        if files:
            for f in files:
                subprocess.run(["git", "-C", str(repo_root), "add", f], check=False)
        else:
            subprocess.run(["git", "-C", str(repo_root), "add", "."], check=False)

        cmd = ["git", "-C", str(repo_root), "commit", "-m", message]
        if amend:
            cmd = ["git", "-C", str(repo_root), "commit", "--amend", "--no-edit"]

        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0 and not amend:
            # Retry once for pre-commit hooks
            if files:
                for f in files:
                    subprocess.run(["git", "-C", str(repo_root), "add", f], check=False)
            else:
                subprocess.run(["git", "-C", str(repo_root), "add", "."], check=False)
            res = subprocess.run(cmd, capture_output=True, text=True)

        if res.returncode == 0:
            try:
                return subprocess.check_output(
                    ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            except Exception:
                return "unknown"
        return "failed"

    def complete_issue(
        self,
        slug: str,
        commit_message: Optional[str] = None,
        should_commit: bool = True,
        push_mission: bool = False,
        solution_explanation: Optional[str] = None,
    ) -> Tuple[Issue, str]:
        """Mark an issue as done. Returns (issue, commit_hash)."""
        issues = self.load_mission()
        target_issue = next((i for i in issues if i.slug == slug), None)
        if not target_issue:
            raise ValueError(f"Issue '{slug}' not found.")

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
        if should_commit:
            msg = commit_message or f"feat: complete {target_issue.slug}"

            # A. Commit Code Changes (Main Repo)
            if self.code_root:
                code_hash = self._git_commit(self.code_root, msg)

            # B. Commit Mission Changes (Mission Repo)
            # If they are different, we perform a second commit
            if self.is_dual_repo and self.mission_root:
                mission_msg = f"task: finalize {target_issue.slug}"
                self._git_commit(self.mission_root, mission_msg)

        # 5. Update issue file with the code hash
        # If we didn't commit, we use the current HEAD or 'pending'
        if code_hash == "unknown" or code_hash == "failed":
            code_hash = self.get_git_commit()

        file_text = final_file.read_text(encoding="utf-8")
        file_text = file_text.replace("<pending-commit-id>", code_hash)
        final_file.write_text(file_text, encoding="utf-8")

        # 6. Amend the mission commit if in dual mode, or the code commit if single mode
        if should_commit:
            if self.is_dual_repo and self.mission_root:
                self._git_commit(
                    self.mission_root, "", amend=True, files=[str(final_file)]
                )
            elif self.code_root:
                self._git_commit(
                    self.code_root, "", amend=True, files=[str(final_file)]
                )

        # 7. Optional Push
        if push_mission and self.mission_root:
            self.push_mission_repo()

        target_issue.status = "completed"
        return target_issue, code_hash

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

        issue_file.write_text(content, encoding="utf-8")

        # Re-extract deps in case they changed
        issues = self.load_mission()
        updated = False
        for i in issues:
            if i.slug == slug:
                i.dependencies = self.extract_deps(issue_file)
                updated = True
                break

        if updated:
            self.save_mission(issues)

        # Return the issue object
        for i in issues:
            if i.slug == slug:
                return i

        # If it was completed, it's not in mission.usv
        return Issue(slug=slug, status="completed")

    def ingest_issues(self) -> Tuple[int, int]:
        """Ingest existing markdown files. Returns (num_new, num_removed)."""
        self.ensure_issues_dir()

        existing_issues = self.load_mission()
        existing_slugs = {i.slug for i in existing_issues}
        present_issues = [i for i in existing_issues if i.status != "unknown"]

        new_issues = []
        for status in ["pending", "draft", "active"]:
            status_dir = self.issues_root / status
            if not status_dir.exists():
                continue

            # File-based
            for issue_file in list(status_dir.glob("*.md")):
                slug = self.slugify(issue_file.stem)
                if slug not in existing_slugs:
                    deps = self.extract_deps(issue_file)
                    new_issues.append(
                        Issue(slug=slug, dependencies=deps, status=status)
                    )
                    existing_slugs.add(slug)

            # Directory-based
            for readme_file in list(status_dir.glob("*/README.md")):
                slug = self.slugify(readme_file.parent.name)
                if slug not in existing_slugs:
                    deps = self.extract_deps(readme_file)
                    new_issues.append(
                        Issue(slug=slug, dependencies=deps, status=status)
                    )
                    existing_slugs.add(slug)

        final_issues = present_issues + new_issues
        self.save_mission(final_issues)
        self.sync_mission()

        return len(new_issues), len(existing_issues) - len(present_issues)
