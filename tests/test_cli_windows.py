from unittest.mock import MagicMock, patch
import sys
from taskagent import cli


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
