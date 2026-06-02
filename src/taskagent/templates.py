from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import subprocess
import tomllib


@dataclass
class DotfileDef:
    path: str
    source: str
    content: Optional[str] = None
    source_path: Optional[Path] = None


@dataclass
class Template:
    name: str
    description: str = ""
    dotfiles: list[DotfileDef] = field(default_factory=list)


def get_template_dir(name: str) -> Path:
    """Resolve the directory for a named template."""
    template_dir = Path(".ta") / "agents" / name
    if not template_dir.is_dir():
        raise RuntimeError(
            f"Template '{name}' not found at {template_dir}. "
            f"Check available templates in .ta/agents/"
        )
    return template_dir


def load_template(name: str) -> Template:
    """Load a template from .ta/agents/<name>/meta.toml."""
    template_dir = get_template_dir(name)
    meta_path = template_dir / "meta.toml"

    if not meta_path.exists():
        raise RuntimeError(f"Template '{name}' has no meta.toml at {meta_path}")

    with open(meta_path, "rb") as f:
        data = tomllib.load(f)

    t = Template(
        name=data.get("name", name),
        description=data.get("description", ""),
    )

    dotfiles_data = data.get("dotfiles", {})
    for rel_path, df_def in dotfiles_data.items():
        source = df_def.get("source", "file")
        content = df_def.get("content")

        if source == "inline":
            if content is None:
                raise RuntimeError(
                    f"Inline dotfile '{rel_path}' in template '{name}' has no content"
                )
            t.dotfiles.append(
                DotfileDef(
                    path=rel_path,
                    source="inline",
                    content=content,
                )
            )
        elif source == "file":
            source_path = template_dir / "dotfiles" / rel_path
            t.dotfiles.append(
                DotfileDef(
                    path=rel_path,
                    source="file",
                    source_path=source_path,
                )
            )
        elif source == "generate":
            t.dotfiles.append(
                DotfileDef(
                    path=rel_path,
                    source="generate",
                )
            )
        elif source.startswith("op://"):
            pass
        else:
            raise RuntimeError(
                f"Unknown dotfile source '{source}' in template '{name}'"
            )

    return t


def materialize_dotfiles(
    template: Template,
    home_dir: Path,
    agent_user: str,
) -> None:
    """Write template dotfiles into the agent's home directory."""
    for df in template.dotfiles:
        if df.source == "inline":
            target_path = home_dir / df.path
            subprocess.run(
                ["sudo", "mkdir", "-p", str(target_path.parent)],
                check=True,
            )
            subprocess.run(
                [
                    "sudo",
                    "chown",
                    f"{agent_user}:{agent_user}",
                    str(target_path.parent),
                ],
                check=True,
            )
            subprocess.run(
                ["sudo", "-u", agent_user, "tee", str(target_path)],
                input=df.content or "",
                capture_output=True,
                text=True,
                check=True,
            )
        elif df.source == "file":
            target_path = home_dir / df.path
            subprocess.run(
                ["sudo", "mkdir", "-p", str(target_path.parent)],
                check=True,
            )
            subprocess.run(
                [
                    "sudo",
                    "chown",
                    f"{agent_user}:{agent_user}",
                    str(target_path.parent),
                ],
                check=True,
            )
            if df.source_path and df.source_path.exists():
                content = df.source_path.read_text()
                subprocess.run(
                    ["sudo", "-u", agent_user, "tee", str(target_path)],
                    input=content,
                    capture_output=True,
                    text=True,
                    check=True,
                )


def has_dotfile(template: Template, path: str) -> bool:
    """Check if a template provides a specific dotfile path."""
    return any(df.path == path for df in template.dotfiles)
