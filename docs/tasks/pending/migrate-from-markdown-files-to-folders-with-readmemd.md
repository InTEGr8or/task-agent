# Migrate from Markdown files to folders with README.md

Create a migration mechanism to move existing items from task-slug.md format to task-slug/README.md format.

This will allow the inclusion of task artifacts, like screenshots, JSON or USV data files, code files, or other artifacts.

We first have to start creating new items with this format. Then, we have to update the transformer logic that moves a task from one state folder to another state folder to use the folder structure instead. We have to update the list and the search and the edit and the view to handle the new format. 

We should probably make a self-healing incremental transformer to transorm the file-based format to the folder based format, and use it on any tasks that are operated on, before doing the operation. 

That means it will affect anything in the pending/ or active/ first. 

The new transformer might be fast enough to run it on every single task in all folders right away. That might simplify things. But it should be a unitary transformer that works on one file first.

Then, we can see if we should apply it to all of them right off the bat. We don't have very large data stores yet where that would be a problem. So running a broad scan would probably be best, but how do we trigger it once and only once? We would have to look for a task file in the root of each of the status folders.
