"""MCP server: lets AI assistants (Claude Desktop, Claude Code, ...) read and manage the
same Obsidian tasks and stopwatch as the widget. Shares core.py and its file locking, so
the widget and the server can run at the same time; the widget picks up changes live.

    pip install 'mcp>=1.2'
    claude mcp add nothing-tasks -- nothing-tasks-mcp
"""
from __future__ import annotations

try:                                                     # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:                                      # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from .core import Stopwatch, VaultError, VaultStore, fmt_hms, load_config

mcp = _Server("nothing-tasks")


def _store() -> VaultStore:
    cfg = load_config()
    return VaultStore(cfg["vault"], cfg["note"])


def _task(t) -> dict:
    return {"id": t.id, "text": t.text, "done": t.done,
            "time_spent": fmt_hms(t.seconds), "seconds": t.seconds}


def _state() -> tuple[VaultStore, Stopwatch]:
    store, sw = _store(), Stopwatch()
    store.list_tasks()                  # also drops legacy ^t- ids
    store.migrate_timer(sw)
    return store, sw


def _commit(store: VaultStore, out: tuple) -> None:
    tid, delta = out
    if tid and delta > 0:
        store.add_time(tid, delta)


@mcp.tool()
def list_tasks(include_done: bool = True) -> list[dict]:
    """List tasks from the Obsidian note (id, text, done, time_spent)."""
    return [_task(t) for t in _store().list_tasks() if include_done or not t.done]


@mcp.tool()
def add_task(text: str) -> dict:
    """Add a task to the Obsidian note. Tags like #work are kept as plain text."""
    return _task(_store().add_task(text))


@mcp.tool()
def complete_task(task_id: str, done: bool = True) -> dict:
    """Mark a task done (or reopen it with done=false)."""
    t = _store().set_done(task_id, done)
    if not t:
        raise VaultError(f"No task with id {task_id}")
    return _task(t)


@mcp.tool()
def delete_task(task_id: str) -> str:
    """Delete a task from the note. Stops the timer if it was timing that task."""
    if not _store().delete_task(task_id):
        raise VaultError(f"No task with id {task_id}")
    sw = Stopwatch()
    if sw.task_id == task_id:
        sw.detach()
    return f"Deleted {task_id}"


@mcp.tool()
def start_timer(task_id: str | None = None) -> dict:
    """Start the stopwatch, optionally on a task. Time is saved to that task when paused."""
    store, sw = _state()
    if task_id and not any(t.id == task_id for t in store.list_tasks()):
        raise VaultError(f"No task with id {task_id}")
    if task_id and sw.task_id != task_id:
        _commit(store, sw.switch(task_id))
    else:
        sw.start(task_id)
    return sw.snapshot()


@mcp.tool()
def pause_timer() -> dict:
    """Pause the stopwatch and write the elapsed time to the current task in Obsidian."""
    store, sw = _state()
    _commit(store, sw.pause())
    return sw.snapshot()


@mcp.tool()
def reset_timer() -> dict:
    """Save elapsed time to the current task, then reset the stopwatch to zero."""
    store, sw = _state()
    _commit(store, sw.reset())
    return sw.snapshot()


@mcp.tool()
def timer_status() -> dict:
    """Current stopwatch state: running, task_id, elapsed."""
    return Stopwatch().snapshot()


def main() -> None:
    mcp.run()          # stdio transport


if __name__ == "__main__":
    main()
