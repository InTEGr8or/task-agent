from unittest.mock import MagicMock, patch
import sys
from types import SimpleNamespace

import pytest

from taskagent import cli


def test_is_native_windows_true_on_win32(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert cli.is_native_windows() is True


def test_is_native_windows_false_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert cli.is_native_windows() is False


def test_is_native_windows_false_on_darwin(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert cli.is_native_windows() is False


def test_is_native_windows_false_on_wsl_linux(monkeypatch):
    """WSL uses Linux Python; must not be treated as native Windows."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert cli.is_native_windows() is False


def test_refuse_if_native_windows_store_ops_exits(monkeypatch):
    monkeypatch.setattr(cli, "is_native_windows", lambda: True)
    console = MagicMock()
    with pytest.raises(SystemExit) as exc_info:
        cli.refuse_if_native_windows_store_ops(console, "ta store migrate")
    assert exc_info.value.code == 1
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list)
    assert "native Windows" in printed
    assert "data root" in printed.lower() or "Data roots" in printed
    assert "symlink" in printed.lower()


def test_refuse_if_native_windows_store_ops_noop_elsewhere(monkeypatch):
    monkeypatch.setattr(cli, "is_native_windows", lambda: False)
    console = MagicMock()
    cli.refuse_if_native_windows_store_ops(console, "ta store migrate")
    console.print.assert_not_called()


def test_cmd_store_migrate_refuses_native_windows(monkeypatch):
    monkeypatch.setattr(cli, "is_native_windows", lambda: True)
    console = MagicMock()
    args = SimpleNamespace(store_command="migrate", dry_run=False, json=False)

    # If refuse did not fire, migrate would try host resolution — fail hard.
    monkeypatch.setattr(
        cli,
        "_store_host_from_args",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not resolve host")),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_store(console, args)
    assert exc_info.value.code == 1
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list)
    assert "ta store migrate" in printed
    assert "native Windows" in printed


def test_cmd_store_data_root_not_refused_on_native_windows(monkeypatch):
    """Other store subcommands must remain available on native Windows."""
    monkeypatch.setattr(cli, "is_native_windows", lambda: True)
    monkeypatch.setattr(
        "taskagent.store_registry.get_data_root",
        lambda: MagicMock(__str__=lambda self: "C:\\Users\\x\\.local\\share\\task-agent"),
    )
    console = MagicMock()
    args = SimpleNamespace(store_command="data-root")
    cli.cmd_store(console, args)
    console.print.assert_called()
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list)
    assert "Refused" not in printed


def test_cmd_eject_mission_refuses_native_windows(monkeypatch):
    monkeypatch.setattr(cli, "is_native_windows", lambda: True)
    console = MagicMock()
    manager = MagicMock()
    # Would be consulted if refuse did not fire
    manager.issues_root = MagicMock()
    manager.issues_root.is_symlink.return_value = False

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_eject_mission(console, manager)
    assert exc_info.value.code == 1
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list)
    assert "ta eject-mission" in printed
    assert "native Windows" in printed
    manager.issues_root.is_symlink.assert_not_called()


def test_get_key_windows_arrow_up(monkeypatch):
    # Mock HAS_MSVCRT to True and HAS_TERMIOS to False
    monkeypatch.setattr(cli, "HAS_MSVCRT", True, raising=False)
    monkeypatch.setattr(cli, "HAS_TERMIOS", False, raising=False)

    # Mock msvcrt.getch
    mock_msvcrt = MagicMock()
    mock_msvcrt.getch.side_effect = [b"\xe0", b"H"]

    # Inject into cli module namespace
    monkeypatch.setattr(cli, "msvcrt", mock_msvcrt, raising=False)

    key = cli.get_key()
    assert key == "\x1b[A"


def test_get_key_windows_arrow_down(monkeypatch):
    monkeypatch.setattr(cli, "HAS_MSVCRT", True, raising=False)
    monkeypatch.setattr(cli, "HAS_TERMIOS", False, raising=False)

    mock_msvcrt = MagicMock()
    mock_msvcrt.getch.side_effect = [b"\xe0", b"P"]
    monkeypatch.setattr(cli, "msvcrt", mock_msvcrt, raising=False)

    key = cli.get_key()
    assert key == "\x1b[B"


def test_get_key_unix_arrow_up(monkeypatch):
    monkeypatch.setattr(cli, "HAS_TERMIOS", True, raising=False)
    monkeypatch.setattr(cli, "HAS_MSVCRT", False, raising=False)

    mock_termios = MagicMock()
    mock_tty = MagicMock()

    # Mock termios functions to avoid IO errors
    mock_termios.tcgetattr.return_value = []
    mock_termios.tcsetattr.return_value = None

    monkeypatch.setattr(cli, "termios", mock_termios, raising=False)
    monkeypatch.setattr(cli, "tty", mock_tty, raising=False)

    # Mock stdin
    mock_stdin = MagicMock()
    mock_stdin.fileno.return_value = 0
    mock_stdin.read.side_effect = ["\x1b", "[A"]
    monkeypatch.setattr(sys, "stdin", mock_stdin)

    with patch("select.select") as mock_select:
        mock_select.return_value = ([True], [], [])
        key = cli.get_key()
        assert key == "\x1b[A"
