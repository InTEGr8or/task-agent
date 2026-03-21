# MCP init breaks in PowerShell

I still get this error when trying to ta init-mcp in PowerShell:



That happens even after rebooting the computer, and running the command with no Gemini chats open.

## Solution

Updated all `subprocess.run` and `subprocess.check_output` calls in `cli.py` and `manager.py` to use `shell=(os.name == "nt")` for Windows compatibility. This ensures that command resolution for scripts like `gemini.cmd` or `uv.cmd` works correctly in PowerShell and Command Prompt. Additionally, updated `ta init-worker` and `ta run` to support Windows-native sidecar worker batch files (`worker.bat`).

---
**Completed in commit:** `<pending-commit-id>`
