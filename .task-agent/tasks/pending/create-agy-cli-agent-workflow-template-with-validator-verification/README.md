# Create agy-cli agent workflow template with validator verification

Introduce a new workflow agent template called 'agy-cli' that integrates with 'agy', 'claude', and 'opencode' CLI commands in non-interactive mode. The worker is prompted to solve the task or decompose it if too complex. A separate validator agent then verifies the correctness and completion of the output.

## Completion Criteria

1. Add an agent workflow template 'agy-cli' that supports running non-interactive worker CLI commands ('agy', 'claude', 'opencode').
2. Implement the prompt structure requesting the agent to complete the task or break it into smaller sub-tasks (reporting actions in task completion notes).
3. Implement a post-completion validator agent that executes after the 'agy-cli' worker finishes to verify task completion.
4. Provide unit or integration tests verifying the workflow template execution and validation logic.
