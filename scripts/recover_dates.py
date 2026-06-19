import os
import subprocess
from pathlib import Path


def get_earliest_date(slug: str) -> str:
    candidate_paths = [
        f"docs/tasks/completed/2026/{slug}/README.md",
        f"docs/tasks/completed/2026/{slug}.md",
        f"docs/tasks/pending/{slug}/README.md",
        f"docs/tasks/pending/{slug}.md",
        f"docs/tasks/draft/{slug}/README.md",
        f"docs/tasks/draft/{slug}.md",
        f"docs/tasks/active/{slug}/README.md",
        f"docs/tasks/active/{slug}.md",
        f"docs/issues/completed/2026/{slug}.md",
        f"docs/issues/pending/{slug}.md",
        f"docs/issues/draft/{slug}.md",
        f"docs/issues/active/{slug}.md",
        f".task-agent/tasks/completed/2026/{slug}/README.md",
        f".task-agent/tasks/pending/{slug}/README.md",
        f".task-agent/tasks/draft/{slug}/README.md",
        f".task-agent/tasks/active/{slug}/README.md",
    ]

    dates = []
    for path in candidate_paths:
        try:
            out = subprocess.check_output(
                ["git", "log", "--all", "--format=%aI", "--reverse", "--", path],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            if out:
                first_line = out.splitlines()[0]
                dates.append(first_line)
        except Exception:
            pass

    if dates:
        dates.sort()
        return dates[0]
    return None


def recover_dates():
    repo_root = Path(__file__).resolve().parent.parent
    tasks_dir = repo_root / ".task-agent" / "tasks"

    if not tasks_dir.exists():
        print(f"Tasks directory not found at: {tasks_dir}")
        return

    updated_count = 0
    # Walk through all directories and find README.md files
    for root, dirs, files in os.walk(tasks_dir):
        root_path = Path(root)

        # Skip internal metadata folder at .task-agent/tasks/.task-agent/
        try:
            rel_parts = root_path.relative_to(tasks_dir).parts
            if ".task-agent" in rel_parts:
                continue
        except ValueError:
            pass

        for file in files:
            if file != "README.md":
                continue

            readme_path = root_path / "README.md"
            slug = root_path.name

            # Skip the root tasks/plan.md or task-agent folder itself if named tasks
            if slug == "tasks":
                continue

            earliest_date = get_earliest_date(slug)
            if earliest_date:
                content = readme_path.read_text(encoding="utf-8")

                # Check if it already has frontmatter
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        frontmatter = parts[1]
                        lines = frontmatter.splitlines()
                        has_created_at = False
                        for i, line in enumerate(lines):
                            if line.strip().startswith("created_at:"):
                                lines[i] = f"created_at: {earliest_date}"
                                has_created_at = True
                                break
                        if not has_created_at:
                            lines.append(f"created_at: {earliest_date}")
                        new_frontmatter = "\n".join(lines) + "\n"
                        new_content = f"---{new_frontmatter}---{parts[2]}"
                    else:
                        new_content = (
                            f"---\ncreated_at: {earliest_date}\n---\n\n" + content
                        )
                else:
                    new_content = f"---\ncreated_at: {earliest_date}\n---\n\n" + content

                readme_path.write_text(new_content, encoding="utf-8")
                print(f"Updated {slug} with date {earliest_date}")
                updated_count += 1
            else:
                print(f"Warning: Could not find Git history date for slug '{slug}'")

    print(f"Finished updating {updated_count} task files.")


if __name__ == "__main__":
    recover_dates()
