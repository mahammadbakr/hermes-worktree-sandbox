"""Tool schemas — what the LLM reads when deciding to call a worktree tool."""

WORKTREE_CREATE = {
    "name": "worktree_create",
    "description": (
        "Create (or reuse) an isolated Git worktree for a task so file edits and commands do not touch "
        "the user's main checkout. Returns a worktree_id used by the other worktree_* tools. Use this "
        "before making a set of related edits you may want to review, discard, or promote. When "
        "terminal.backend is 'worktree', a worktree is also created automatically for each task."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "workspace": {
                "type": "string",
                "description": "Path inside the Git repo to isolate. Defaults to the session's working directory.",
            },
            "task_id": {
                "type": "string",
                "description": "Stable id for this task/session; the same id reuses the same worktree. Defaults to 'default'.",
            },
            "base": {
                "type": "string",
                "description": "Optional commit-ish to branch from. Defaults to the repo's current HEAD.",
            },
        },
        "required": [],
    },
}

WORKTREE_STATUS = {
    "name": "worktree_status",
    "description": (
        "List managed worktrees and, for each, the changed files with '+added / -deleted' line stats and "
        "whether the worktree is clean. Use this to see pending work before deciding to promote or discard."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worktree_id": {
                "type": "string",
                "description": "Show detail for one worktree. Omit to list every active worktree.",
            },
            "workspace": {
                "type": "string",
                "description": "Only list worktrees for this Git repo. Defaults to the session's working directory.",
            },
            "include_inactive": {
                "type": "boolean",
                "description": "Include worktrees already promoted or discarded.",
                "default": False,
            },
        },
        "required": [],
    },
}

WORKTREE_DIFF = {
    "name": "worktree_diff",
    "description": (
        "Return the unified diff of a worktree against its base commit, plus a per-file change summary. "
        "Use this to review exactly what would be promoted into the user's checkout."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worktree_id": {"type": "string", "description": "The worktree id to diff."},
            "path": {"type": "string", "description": "Optional repo-relative path to limit the diff to one file."},
        },
        "required": ["worktree_id"],
    },
}

WORKTREE_PROMOTE = {
    "name": "worktree_promote",
    "description": (
        "Apply a worktree's changes back into the user's main checkout. Files the user edited since the "
        "worktree was created are reported as conflicts and left untouched unless force is true. A "
        "timestamped backup of every overwritten file is written before it is replaced."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "worktree_id": {"type": "string", "description": "The worktree id whose changes to apply."},
            "force": {
                "type": "boolean",
                "description": "Overwrite conflicting host edits (a backup is still written). Default false.",
                "default": False,
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional subset of repo-relative paths to promote instead of every change.",
            },
        },
        "required": ["worktree_id"],
    },
}

ALL_SCHEMAS = [WORKTREE_CREATE, WORKTREE_STATUS, WORKTREE_DIFF, WORKTREE_PROMOTE]
