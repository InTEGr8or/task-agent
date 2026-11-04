"""WSL path aliases: one Linux store, a Windows UNC, no NTFS copy."""

from pathlib import Path

from taskagent.store_registry import (
    drvfs_to_windows,
    host_path_aliases,
    linux_to_wsl_unc,
)


def test_drvfs_to_windows():
    assert (
        drvfs_to_windows(Path("/mnt/c/Users/xgenx/repos/image-annex"))
        == r"C:\Users\xgenx\repos\image-annex"
    )


def test_linux_store_unc_and_not_drvfs(monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Debian")
    assert (
        linux_to_wsl_unc(Path("/home/mstouffer/.local/share/task-agent"))
        == r"\\wsl$\Debian\home\mstouffer\.local\share\task-agent"
    )
    assert linux_to_wsl_unc(Path("/mnt/c/Users/xgenx")) is None


def test_host_aliases_include_windows_path():
    aliases = host_path_aliases(Path("/mnt/c/Users/xgenx/repos/image-annex"))
    assert aliases[0].endswith("/image-annex")
    assert r"C:\Users\xgenx\repos\image-annex" in aliases
