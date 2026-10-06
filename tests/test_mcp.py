import asyncio

import pytest

pytest.importorskip("mcp")


def test_tools_registered_and_roundtrip(env):
    from nothing_tasks import mcp_server as m
    names = {t.name for t in asyncio.run(m.mcp.list_tools())}
    assert {"list_tasks", "add_task", "complete_task", "delete_task", "start_timer",
            "pause_timer", "reset_timer", "timer_status"} <= names

    t = m.add_task("write report #work")
    assert m.list_tasks()[0]["text"] == "write report #work"
    m.start_timer(t["id"])
    assert m.timer_status()["running"] and m.timer_status()["task_id"] == t["id"]
    from nothing_tasks.core import Stopwatch
    sw = Stopwatch(); sw.accumulated, sw.started_at = 90, 0   # pretend 90s elapsed
    sw.running = False; sw._save()
    m.pause_timer()
    assert m.list_tasks()[0]["seconds"] == 90
    m.complete_task(t["id"])
    assert m.list_tasks(include_done=False) == []
    m.delete_task(t["id"])
    assert m.list_tasks() == []
    with pytest.raises(m.VaultError):
        m.complete_task("t-000000")
