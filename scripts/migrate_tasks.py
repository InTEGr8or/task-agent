import os
from pathlib import Path
import shutil


def migrate_tasks():
    repo_root = Path(__file__).resolve().parent.parent
    tasks_dir = repo_root / ".task-agent" / "tasks"

    if not tasks_dir.exists():
        print(f"Tasks directory not found at: {tasks_dir}")
        return

    # Walk through all directories inside tasks_dir (completed, pending, active, draft, etc.)
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
            if not file.endswith(".md") or file == "plan.md" or file == "README.md":
                continue

            file_path = root_path / file
            slug = file_path.stem
            matching_dir = root_path / slug

            if matching_dir.exists() and matching_dir.is_dir():
                # If the matching folder exists, check if it has README.md
                readme_path = matching_dir / "README.md"
                if readme_path.exists():
                    print(
                        f"Duplicate found: Removing loose file '{file}' since folder '{slug}/README.md' exists."
                    )
                    file_path.unlink()
                else:
                    # Folder exists but no README.md, move the file into it
                    print(
                        f"Moving loose file '{file}' into existing folder '{slug}/README.md'."
                    )
                    shutil.move(str(file_path), str(readme_path))
            else:
                # Create the folder and move the file
                print(
                    f"Migrating loose file '{file}' to folder format '{slug}/README.md'."
                )
                matching_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file_path), str(matching_dir / "README.md"))


if __name__ == "__main__":
    migrate_tasks()
