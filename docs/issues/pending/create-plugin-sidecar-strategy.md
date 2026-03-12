# The "Plugin" Strategy

To get the power without the bloat, I suggest an Interface-first approach:


   1. Core ta remains the "State Machine": Keep the current logic for pending, active, and
      done. It should remain the source of truth for the filesystem.
   2. ta start as the Bridge: This command should do the "infrastructure" work we
      planned—create the git branch and set up the .gwt/ worktree.
   3. ta run as the Executor: This is where the ADK samples come in. Instead of baking the
      ADK into the ta binary, ta run could:
       * Look for a .taskagent/worker.py in the local repo.
       * If that worker uses the ADK standard, ta run simply invokes it.
       * The worker performs the work and, upon success, calls ta done to signal back to
         Mission Control.


  Conclusion:

  Don't merge the ADK into the core task-agent codebase. Instead, use the ADK samples to
  build a Reference Worker. This keeps your CLI simple for the two apps you're already
  using, but allows you to point an agent at a pending task and say "Go" via the ta run
  command.

[Gemini ADK Sample - Python](https://github.com/google/adk-samples/tree/main/python)
