from pathlib import Path


def clean_duplicates():
    # Target the local .task-agent/tasks/completed/2026/ folder relative to repo root
    repo_root = Path(__file__).resolve().parent.parent
    completed_dir = repo_root / ".task-agent" / "tasks" / "completed" / "2026"

    if not completed_dir.exists():
        print(f"Completed directory not found at: {completed_dir}")
        return

    loose_files = []
    folders = set()

    for item in completed_dir.iterdir():
        if item.is_file() and item.suffix == ".md":
            loose_files.append(item)
        elif item.is_dir():
            folders.add(item.name)

    print(f"Found {len(loose_files)} loose markdown files and {len(folders)} folders.")

    removed_count = 0
    for file_path in loose_files:
        slug = file_path.stem
        if slug in folders:
            print(
                f"Removing duplicate loose file: {file_path.name} (folder '{slug}/' already exists)"
            )
            file_path.unlink()
            removed_count += 1

    print(f"Removed {removed_count} duplicate loose markdown files.")


if __name__ == "__main__":
    clean_duplicates()
