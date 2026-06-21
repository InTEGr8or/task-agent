import os
import sys
import subprocess
import asyncio
import json
import shutil
from pathlib import Path
from typing import Optional
from rich.console import Console
from dotenv import load_dotenv

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.models import Gemini
from google.adk.tools.tool_context import ToolContext

# Load environment variables
load_dotenv()

console = Console()

# --- Secret Management (1Password) ---


async def get_1password_secret(reference: str) -> Optional[str]:
    """Retrieve a secret from 1Password using the SDK."""
    try:
        from onepassword import Client, DesktopAuth

        # Use DesktopAuth by default for local development.
        # If OP_SERVICE_ACCOUNT_TOKEN is present, we could use that too.
        token = os.getenv("OP_SERVICE_ACCOUNT_TOKEN")
        if token:
            client = await Client.authenticate(
                auth=token,
                integration_name="task-agent-worker",
                integration_version="0.1.0",
            )
        else:
            client = await Client.authenticate(
                auth=DesktopAuth(),
                integration_name="task-agent-worker",
                integration_version="0.1.0",
            )

        return await client.secrets.resolve(reference)
    except ImportError:
        console.print(
            "[yellow]onepassword-sdk not installed. Skipping 1Password retrieval.[/yellow]"
        )
    except Exception as e:
        console.print(f"[yellow]Failed to retrieve secret from 1Password: {e}[/yellow]")
    return None


def get_google_api_key() -> str:
    """Get the Google API Key from environment or 1Password."""
    # 1. Check environment
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        return api_key

    # 2. Check 1Password
    ref = os.getenv("OP_SECRET_REFERENCE", "op://Personal/Gemini/api-key")
    console.print(
        f"[blue]Attempting to fetch GOOGLE_API_KEY from 1Password ({ref})...[/blue]"
    )

    api_key = asyncio.run(get_1password_secret(ref))
    if api_key:
        os.environ["GOOGLE_API_KEY"] = api_key
        return api_key

    console.print(
        "[red]Error: GOOGLE_API_KEY not found in environment or 1Password.[/red]"
    )
    sys.exit(1)


# --- Tools ---


def _get_abs_path(path: str, root: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return Path(root) / p


def read_file_tool(path: str, tool_context: ToolContext) -> str:
    """Read the content of a file. Path is relative to TA_ROOT."""
    root = tool_context.state.get("TA_ROOT", ".")
    abs_path = _get_abs_path(path, root)
    try:
        return abs_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file {path}: {e}"


def write_file_tool(path: str, content: str, tool_context: ToolContext) -> str:
    """Write content to a file. Path is relative to TA_ROOT. Overwrites existing files."""
    root = tool_context.state.get("TA_ROOT", ".")
    abs_path = _get_abs_path(path, root)
    try:
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to {path}: {e}"


def run_command_tool(command: str, tool_context: ToolContext) -> str:
    """Run a shell command in the TA_ROOT directory."""
    root = tool_context.state.get("TA_ROOT", ".")
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, cwd=root
        )
        output = result.stdout
        if result.stderr:
            output += f"\n--- STDERR ---\n{result.stderr}"
        return output if output else f"(Exit code: {result.returncode}, No output)"
    except Exception as e:
        return f"Error running command: {e}"


def check_success_tool(passed: bool, message: str, tool_context: ToolContext) -> str:
    """Signals whether the validation passed or failed.
    If 'passed' is True, the loop terminates.
    If 'passed' is False, the loop continues with the provided 'message' as feedback.
    """
    if passed:
        tool_context.actions.escalate = True
        return f"Validation Passed: {message}. Ending loop."
    else:
        return f"Validation Failed: {message}. Requesting fix."


# --- Helpers ---


def load_instruction(name: str) -> str:
    """Load agent instruction from a markdown file."""
    path = Path(__file__).parent / "instructions" / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


def load_profile(name: str) -> dict:
    """Load model profile from a JSON file."""
    path = Path(__file__).parent / "profiles" / f"{name}.json"
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_model(config: dict):
    """Factory to create a model instance based on profile config."""
    provider = config.get("provider", "google")
    model_id = config.get("model_id", "gemini-2.0-flash")

    if provider == "google":
        return Gemini(model_id=model_id)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


# --- Agent Definitions ---

# Load profile
profile_name = os.getenv("TA_PROFILE", "default")
profile = load_profile(profile_name)

# Initialize API Key
get_google_api_key()

# 1. Manager: High-level planner
manager = LlmAgent(
    name="Manager",
    model=get_model(profile["manager"]),
    instruction=load_instruction("manager"),
    output_key="master_plan",
)

# 2. Worker: Implementation agent
worker = LlmAgent(
    name="Worker",
    model=get_model(profile["worker"]),
    instruction=load_instruction("worker"),
    tools=[read_file_tool, write_file_tool, run_command_tool],
)

# 3. Validator: Quality assurance agent
validator = LlmAgent(
    name="Validator",
    model=get_model(profile["validator"]),
    instruction=load_instruction("validator"),
    tools=[run_command_tool, check_success_tool],
    output_key="validation_feedback",
)

# --- Orchestration ---

refinement_loop = LoopAgent(
    name="RefinementLoop", sub_agents=[worker, validator], max_iterations=5
)

root_agent = SequentialAgent(
    name="ADKSidecarRoot", sub_agents=[manager, refinement_loop]
)


def get_available_cli() -> Optional[str]:
    for cli in ["agy", "claude", "opencode"]:
        if shutil.which(cli):
            return cli
    return None


def read_task_description(file_path: str) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except Exception as e:
        return f"Could not read task description from {file_path}: {e}"


def run_agy_cli_workflow(slug: str, file_path: str, project_root: str):
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    cli = os.environ.get("TA_TEST_CLI") or get_available_cli()
    if not cli:
        console.print(
            "[red]Error: No available CLI found. Checked for agy, claude, opencode.[/red]"
        )
        sys.exit(1)

    task_desc = read_task_description(file_path)
    feedback = "Initial run. No feedback yet."
    validation_passed = False
    solution = "Task completed by agy-cli worker."

    for iteration in range(1, 6):
        console.print(
            f"[bold blue]Iteration {iteration}/5 for agy-cli worker[/bold blue]"
        )

        # 1. Construct prompt
        if iteration == 1:
            prompt = (
                f"Solve the following task in the codebase:\n\n"
                f"{task_desc}\n\n"
                f"Instructions:\n"
                f"1. Attempt to solve the task or make appropriate changes to the codebase.\n"
                f"2. If the task is too complex, break it into smaller sub-tasks (decompose it) and report these actions in the task completion notes.\n"
            )
        else:
            prompt = (
                f"The previous attempt to solve the task failed validation with the following feedback:\n"
                f"{feedback}\n\n"
                f"Please address this feedback and solve the task:\n\n"
                f"{task_desc}\n\n"
                f"Instructions:\n"
                f"1. Attempt to solve the task or make appropriate changes to the codebase.\n"
                f"2. If the task is too complex, break it into smaller sub-tasks (decompose it) and report these actions in the task completion notes.\n"
            )

        # 2. Build the command
        if cli == "agy":
            cmd = ["agy", "-p", prompt]
        elif cli == "claude":
            cmd = ["claude", "-p", prompt]
        elif cli == "opencode":
            cmd = ["opencode", "run", prompt]
        else:
            # Fallback for custom/mock test CLI
            cmd = [cli, prompt]

        # 3. Run the CLI worker
        console.print(f"[blue]Running worker command: {' '.join(cmd[:3])}...[/blue]")
        try:
            # Run in the current directory (which is the worktree path)
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            worker_output = result.stdout
            if result.stderr:
                worker_output += f"\n--- STDERR ---\n{result.stderr}"
            console.print("[green]Worker command finished successfully.[/green]")
        except subprocess.CalledProcessError as e:
            worker_output = e.stdout or ""
            if e.stderr:
                worker_output += f"\n--- STDERR ---\n{e.stderr}"
            console.print(
                f"[yellow]Worker command failed with exit code {e.returncode}.[/yellow]"
            )
            # Check if this failure was due to not being logged in or missing credentials
            combined_output = worker_output.lower()
            auth_keywords = [
                "not logged in",
                "login required",
                "please log in",
                "please login",
                "gcloud auth",
                "unauthenticated",
                "unauthorized",
                "credentials",
                "sign in",
            ]
            if any(kw in combined_output for kw in auth_keywords):
                console.print(
                    "[red]Error: Worker command failed due to authentication/login issue.[/red]"
                )
                console.print(f"[red]{worker_output.strip()}[/red]")
                sys.exit(1)

            console.print("[yellow]Proceeding to validation.[/yellow]")
        except Exception as e:
            console.print(f"[red]Error executing worker command: {e}[/red]")
            worker_output = f"Execution error: {e}"

        # 4. Run the post-completion validator
        console.print("[blue]Running post-completion validator...[/blue]")
        runner = InMemoryRunner(agent=validator)
        user_message = types.Content(
            parts=[types.Part(text=f"Verify the changes for issue {slug}")]
        )

        # Run validation
        for event in runner.run(
            user_id="user",
            session_id=f"val-session-{iteration}",
            new_message=user_message,
            state_delta={
                "TA_SLUG": slug,
                "TA_FILE": file_path,
                "TA_ROOT": project_root,
                "master_plan": f"Executed CLI worker: {cli}",
                "validation_feedback": feedback,
            },
        ):
            if event.actions and event.actions.escalate:
                validation_passed = True
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        console.print(f"[{event.author}]: {part.text}")

        # Retrieve final validation feedback
        session = runner.session_service._get_session_impl(
            app_name=runner.app_name,
            user_id="user",
            session_id=f"val-session-{iteration}",
        )
        if session:
            feedback = session.state.get(
                "validation_feedback", "Validation failed without feedback."
            )
            solution = feedback

        if validation_passed:
            console.print("[bold green]Validation passed successfully![/bold green]")
            break
        else:
            console.print(
                f"[bold yellow]Validation failed. Feedback: {feedback}[/bold yellow]"
            )

    # Post Merge Request
    mr_dir = Path(project_root) / "docs" / "tasks" / "mr"
    mr_dir.mkdir(parents=True, exist_ok=True)
    mr_file = mr_dir / f"{slug}.md"

    console.print(f"[blue]Posting Merge Request to {mr_file}...[/blue]")
    mr_file.write_text(solution, encoding="utf-8")

    console.print(
        f"[bold green]Task '{slug}' is ready for review. Run 'ta mr list' to see it.[/bold green]"
    )


def main():
    slug = os.environ.get("TA_SLUG")
    file_path = os.environ.get("TA_FILE")
    project_root = os.environ.get("TA_ROOT")

    if not slug or not file_path or not project_root:
        console.print(
            "[red]Error: Missing required environment variables TA_SLUG, TA_FILE, or TA_ROOT.[/red]"
        )
        sys.exit(1)

    console.print(f"[bold blue]ADK Sidecar starting for issue: {slug}[/bold blue]")

    # Determine template name from .ta-agent.json in the current working directory
    template_name = "adk"
    meta_path = Path(".ta-agent.json")
    if meta_path.exists():
        try:
            with open(meta_path, "r") as f:
                meta = json.load(f)
                template_name = meta.get("template", "adk")
        except Exception:
            pass

    if template_name == "agy-cli":
        run_agy_cli_workflow(slug, file_path, project_root)
        return

    try:
        from google.adk.runners import InMemoryRunner
        from google.genai import types

        runner = InMemoryRunner(agent=root_agent)
        user_message = types.Content(
            parts=[types.Part(text=f"Solve issue {slug} based on {file_path}")]
        )

        # Run the agent and consume the events
        for event in runner.run(
            user_id="user",
            session_id="session",
            new_message=user_message,
            state_delta={
                "TA_SLUG": slug,
                "TA_FILE": file_path,
                "TA_ROOT": project_root,
                "validation_feedback": "Initial run. No feedback yet.",
            },
        ):
            if event.content and event.content.parts:
                for part in event.content.parts:
                    if part.text:
                        console.print(f"[{event.author}]: {part.text}")

        # Retrieve final state from session service
        session = runner.session_service._get_session_impl(
            app_name=runner.app_name,
            user_id="user",
            session_id="session",
        )
        state = session.state if session else {}
        console.print("[bold green]ADK Sidecar execution finished.[/bold green]")

        solution = state.get("validation_feedback", "Task completed by ADK worker.")

        # Post Merge Request
        mr_dir = Path(project_root) / "docs" / "tasks" / "mr"
        mr_dir.mkdir(parents=True, exist_ok=True)
        mr_file = mr_dir / f"{slug}.md"

        console.print(f"[blue]Posting Merge Request to {mr_file}...[/blue]")
        mr_file.write_text(solution, encoding="utf-8")

        console.print(
            f"[bold green]Task '{slug}' is ready for review. Run 'ta mr list' to see it.[/bold green]"
        )

    except Exception as e:
        console.print(f"[red]Error during ADK execution: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
