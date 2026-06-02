import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from taskagent import templates


def ensure_sudo() -> None:
    """Check that sudo is available and the user can use it."""
    if not shutil.which("sudo"):
        raise RuntimeError("sudo is required but not found on this system.")

    res = subprocess.run(
        ["sudo", "-n", "true"],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            "sudo requires a password or is not configured. "
            "Ensure your user has passwordless sudo or run 'sudo -v' first."
        )


def _system_user_exists(name: str) -> bool:
    """Check if a system user exists."""
    res = subprocess.run(
        ["id", name],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


def init_agent(
    name: str,
    template_name: Optional[str] = None,
) -> dict:
    """Create a dedicated agent Linux user.

    Returns a dict with paths to the created resources.
    """
    agent_user = f"agent-{name}"
    ensure_sudo()

    if _system_user_exists(agent_user):
        raise RuntimeError(f"Agent user '{agent_user}' already exists.")

    home_dir = Path(f"/home/{agent_user}")

    # 1. Create the system user with explicit home directory
    res = subprocess.run(
        [
            "sudo",
            "useradd",
            "--system",
            "--no-create-home",
            "--home-dir",
            str(home_dir),
            "--shell",
            "/bin/bash",
            agent_user,
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError(
            f"Failed to create user '{agent_user}': {res.stderr.strip()}"
        )

    subprocess.run(
        ["sudo", "mkdir", "-p", str(home_dir)],
        check=True,
    )
    ssh_dir = home_dir / ".ssh"
    subprocess.run(
        ["sudo", "mkdir", "-m", "0700", "-p", str(ssh_dir)],
        check=True,
    )

    # 2. Chown home to agent before running commands as agent
    subprocess.run(
        ["sudo", "chown", "-R", f"{agent_user}:{agent_user}", str(home_dir)],
        check=True,
    )

    # 3. Generate SSH key
    key_path = ssh_dir / "id_ed25519"
    subprocess.run(
        [
            "sudo",
            "-u",
            agent_user,
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(key_path),
            "-N",
            "",
            "-q",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # 4. Write .gitconfig
    gitconfig = home_dir / ".gitconfig"
    gitconfig_content = (
        f"[user]\n\tname = Agent {name}\n\temail = agent-{name}@localhost\n"
    )

    # Add safe.directory for worktrees
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
        gitconfig_content += f"[safe]\n\tdirectory = {repo_root}/.gwt/*\n"
    except Exception:
        pass

    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(gitconfig)],
        input=gitconfig_content,
        capture_output=True,
        text=True,
        check=True,
    )

    # 4b. Materialize template dotfiles on top of defaults (overrides)
    if template_name:
        template = templates.load_template(template_name)
        templates.materialize_dotfiles(template, home_dir, agent_user)

    # 4b. Provision tools into agent's ~/.local/bin/
    local_bin = home_dir / ".local" / "bin"
    subprocess.run(
        ["sudo", "mkdir", "-p", str(local_bin)],
        check=True,
    )
    # Find uv even when running as root (via sudo) — check SUDO_USER's home
    uv_path = None
    human_user = os.environ.get("SUDO_USER")
    if human_user:
        candidate = Path(f"/home/{human_user}/.local/bin/uv")
        if candidate.exists():
            uv_path = str(candidate)
    if not uv_path:
        uv_path = shutil.which("uv")
    if uv_path:
        subprocess.run(
            ["sudo", "ln", "-sf", uv_path, str(local_bin / "uv")],
            check=True,
        )

    # 4c. Create .profile that adds ~/.local/bin to PATH
    profile = home_dir / ".profile"
    profile_content = (
        'case ":${PATH}:" in\n'
        '  *:"$HOME/.local/bin":*)\n'
        "    ;;\n"
        "  *)\n"
        '    PATH="$HOME/.local/bin:$PATH"\n'
        "    ;;\n"
        "esac\n"
        "export PATH\n"
    )
    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(profile)],
        input=profile_content,
        capture_output=True,
        text=True,
        check=True,
    )

    # 5. Install sudoers drop-in
    sudoers_path = Path(f"/etc/sudoers.d/ta-agent-{name}")
    ta_path = shutil.which("ta") or "/usr/local/bin/ta"
    sudoers_content = (
        f"%{agent_user} ALL=(ALL) NOPASSWD: {ta_path}\n"
        f"%{agent_user} ALL=(ALL) NOPASSWD: {ta_path} run *\n"
    )

    subprocess.run(
        ["sudo", "tee", str(sudoers_path)],
        input=sudoers_content,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["sudo", "chmod", "0440", str(sudoers_path)],
        check=True,
    )

    # 7. Write meta.json
    meta = {
        "name": name,
        "user": agent_user,
        "home": str(home_dir),
        "created_at": __import__("datetime").datetime.now().isoformat(),
    }
    if template_name:
        meta["template"] = template_name
    meta_path = home_dir / ".ta" / "meta.json"
    subprocess.run(
        ["sudo", "mkdir", "-p", str(meta_path.parent)],
        check=True,
    )
    subprocess.run(
        ["sudo", "chown", f"{agent_user}:{agent_user}", str(meta_path.parent)],
        check=True,
    )
    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(meta_path)],
        input=__import__("json").dumps(meta, indent=2),
        capture_output=True,
        text=True,
        check=True,
    )

    return {
        "user": agent_user,
        "home": str(home_dir),
        "ssh_key": str(key_path),
        "ssh_pub": str(key_path) + ".pub",
        "gitconfig": str(gitconfig),
        "profile": str(profile),
        "local_bin": str(local_bin),
        "sudoers": str(sudoers_path),
    }


def destroy_agent(name: str) -> None:
    """Remove a previously created agent user."""
    agent_user = f"agent-{name}"
    ensure_sudo()

    if not _system_user_exists(agent_user):
        raise RuntimeError(f"Agent user '{agent_user}' does not exist.")

    # Remove sudoers drop-in
    sudoers_path = Path(f"/etc/sudoers.d/ta-agent-{name}")
    if sudoers_path.exists():
        subprocess.run(
            ["sudo", "rm", str(sudoers_path)],
            check=True,
        )

    # Remove user and home directory
    subprocess.run(
        ["sudo", "userdel", "-r", agent_user],
        capture_output=True,
        text=True,
        check=True,
    )


def get_agent_user(name: str) -> str:
    """Return the agent user name, verifying it exists."""
    agent_user = f"agent-{name}"
    if not _system_user_exists(agent_user):
        raise RuntimeError(
            f"Agent user '{agent_user}' does not exist. "
            f"Run 'ta init-agent {name}' first."
        )
    return agent_user


def get_worktree_path(slug: str) -> Path:
    """Get the worktree path for a given slug."""
    return Path(".gwt") / slug


def set_worktree_permissions(slug: str, agent_user: str) -> None:
    """Set group and permissions on a worktree so the agent user can access it."""
    worktree_path = get_worktree_path(slug)
    if not worktree_path.exists():
        raise RuntimeError(f"Worktree not found at {worktree_path}")

    subprocess.run(
        ["sudo", "chgrp", "-R", agent_user, str(worktree_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["sudo", "chmod", "-R", "g+rwX", str(worktree_path)],
        check=True,
        capture_output=True,
    )


def _per_task_agent_name(task_slug: str, template_name: str) -> str:
    """Generate a unique agent user name for a per-task agent."""
    clean_slug = re.sub(r"[^a-zA-Z0-9]", "", task_slug)[:15]
    h = hashlib.sha256(f"{task_slug}:{template_name}".encode()).hexdigest()[:8]
    return f"agent-{clean_slug}-{h}"


def _per_task_meta_path(task_slug: str) -> Path:
    """Path to the per-task agent metadata file (inside the worktree)."""
    return Path(".gwt") / task_slug / ".ta-agent.json"


def init_per_task_agent(task_slug: str, template_name: str) -> dict:
    """Create a dedicated agent user for a single task.

    The user's home directory is set to the worktree path so no extra
    /home/agent-* directory is created.  Dotfiles from the template are
    written directly into the worktree.
    """
    ensure_sudo()
    agent_user = _per_task_agent_name(task_slug, template_name)
    clean_slug = re.sub(r"[^a-zA-Z0-9]", "", task_slug)[:15]
    h = hashlib.sha256(f"{task_slug}:{template_name}".encode()).hexdigest()[:8]
    worktree = Path(".gwt") / task_slug

    if not worktree.is_dir():
        raise RuntimeError(
            f"Worktree not found at {worktree}. Create it with 'ta start {task_slug}' first."
        )

    worktree_abs = worktree.resolve()

    if _system_user_exists(agent_user):
        raise RuntimeError(
            f"Per-task agent '{agent_user}' already exists for '{task_slug}'."
        )

    # Create system user with --no-create-home, home = worktree
    subprocess.run(
        [
            "sudo",
            "useradd",
            "--system",
            "--no-create-home",
            "--home-dir",
            str(worktree_abs),
            "--shell",
            "/bin/bash",
            agent_user,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Chown worktree to the agent so sudo -u agent_user tee can write
    subprocess.run(
        ["sudo", "chown", "-R", f"{agent_user}:{agent_user}", str(worktree)],
        check=True,
    )

    # Generate SSH key in worktree .ssh/
    ssh_dir = worktree / ".ssh"
    subprocess.run(
        ["sudo", "mkdir", "-m", "0700", "-p", str(ssh_dir)],
        check=True,
    )
    subprocess.run(
        ["sudo", "chown", f"{agent_user}:{agent_user}", str(ssh_dir)],
        check=True,
    )
    key_path = ssh_dir / "id_ed25519"
    subprocess.run(
        [
            "sudo",
            "-u",
            agent_user,
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(key_path),
            "-N",
            "",
            "-q",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    # Write .gitconfig
    gitconfig = worktree / ".gitconfig"
    gitconfig_content = (
        f"[user]\n\tname = Task {task_slug}\n\temail = agent-{task_slug}@localhost\n"
    )
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
        gitconfig_content += f"[safe]\n\tdirectory = {repo_root}/.gwt/*\n"
    except Exception:
        pass
    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(gitconfig)],
        input=gitconfig_content,
        capture_output=True,
        text=True,
        check=True,
    )

    # Materialize template dotfiles on top of defaults
    template = templates.load_template(template_name)
    templates.materialize_dotfiles(template, worktree, agent_user)

    # Provision uv
    local_bin = worktree / ".local" / "bin"
    subprocess.run(
        ["sudo", "mkdir", "-p", str(local_bin)],
        check=True,
    )
    uv_path: str | None = None
    human_user = os.environ.get("SUDO_USER")
    if human_user:
        candidate = Path(f"/home/{human_user}/.local/bin/uv")
        if candidate.exists():
            uv_path = str(candidate)
    if not uv_path:
        uv_path = shutil.which("uv")
    if uv_path:
        subprocess.run(
            ["sudo", "ln", "-sf", uv_path, str(local_bin / "uv")],
            check=True,
        )

    # .profile
    profile = worktree / ".profile"
    profile_content = (
        'case ":${PATH}:" in\n'
        '  *:"$HOME/.local/bin":*)\n    ;;\n  *)\n'
        '    PATH="$HOME/.local/bin:$PATH"\n    ;;\n'
        "esac\n"
        "export PATH\n"
    )
    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(profile)],
        input=profile_content,
        capture_output=True,
        text=True,
        check=True,
    )

    # sudoers drop-in
    sudoers_path = Path(f"/etc/sudoers.d/ta-{clean_slug}-{h}")
    ta_path = shutil.which("ta") or "/usr/local/bin/ta"
    sudoers_content = (
        f"%{agent_user} ALL=(ALL) NOPASSWD: {ta_path}\n"
        f"%{agent_user} ALL=(ALL) NOPASSWD: {ta_path} run *\n"
    )
    subprocess.run(
        ["sudo", "tee", str(sudoers_path)],
        input=sudoers_content,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["sudo", "chmod", "0440", str(sudoers_path)],
        check=True,
    )

    # Store metadata
    store_per_task_agent_meta(task_slug, agent_user, template_name)

    return {
        "user": agent_user,
        "home": str(worktree),
        "ssh_key": str(key_path),
        "ssh_pub": str(key_path) + ".pub",
        "gitconfig": str(gitconfig),
        "profile": str(profile),
        "local_bin": str(local_bin),
        "sudoers": str(sudoers_path),
    }


def store_per_task_agent_meta(
    task_slug: str, agent_user: str, template_name: str
) -> None:
    """Write per-task agent metadata into the worktree using sudo tee."""
    meta_path = _per_task_meta_path(task_slug)
    meta = {
        "user": agent_user,
        "template": template_name,
        "task_slug": task_slug,
    }
    subprocess.run(
        ["sudo", "mkdir", "-p", str(meta_path.parent)],
        check=True,
    )
    subprocess.run(
        ["sudo", "-u", agent_user, "tee", str(meta_path)],
        input=json.dumps(meta, indent=2),
        capture_output=True,
        text=True,
        check=True,
    )


def load_per_task_agent_meta(task_slug: str) -> dict | None:
    """Read per-task agent metadata, or None if it doesn't exist."""
    meta_path = _per_task_meta_path(task_slug)
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text())


def destroy_per_task_agent(task_slug: str) -> None:
    """Destroy a per-task agent user and clean up metadata."""
    meta = load_per_task_agent_meta(task_slug)
    if not meta:
        return

    agent_user = meta["user"]
    ensure_sudo()

    # Remove sudoers drop-in — reconstruct name from meta
    if _system_user_exists(agent_user):
        subprocess.run(
            ["sudo", "userdel", "-r", agent_user],
            capture_output=True,
            text=True,
        )

    # Clean up sudoers
    meta_path = _per_task_meta_path(task_slug)
    name_part = agent_user.removeprefix("agent-")
    sudoers_path = Path(f"/etc/sudoers.d/ta-{name_part}")
    if sudoers_path.exists():
        subprocess.run(["sudo", "rm", str(sudoers_path)], check=True)

    # Remove metadata file
    if meta_path.exists():
        meta_path.unlink()
