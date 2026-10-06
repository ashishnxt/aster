"""The notepad frame must stay exactly as wide as the pill, and the clock/list centred in it, no matter
which page was visited before (settings, a task's detail) or how wide a page's content wants to be."""
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("xvfb-run"), reason="xvfb-run not installed")

SCRIPT = textwrap.dedent("""
    import os, sys, time
    os.environ["GDK_BACKEND"] = "x11"
    from gi.repository import Gtk
    from nothing_tasks.ui import Island
    scale = float(sys.argv[1])
    w = Island()
    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            while Gtk.events_pending(): Gtk.main_iteration()
            time.sleep(0.01)
    def centred(tag):
        w.ex.a = w.ap.a = None; w.ex.v = w.ap.v = 1.0; w._apply(); pump(0.4)
        frame = w.exp_box.get_allocated_width()
        dx, _ = w.display.translate_coordinates(w.exp_box, 0, 0)
        left, right = dx, frame - (dx + w.display.get_allocated_width())
        assert frame == w.ew, (tag, "frame", frame, "pill", w.ew)
        assert abs(left - right) <= 1, (tag, "clock gaps", left, right)
        rows = w.list.get_children()
        if rows:
            rx, _ = rows[0].translate_coordinates(w.exp_box, 0, 0)
            assert abs(rx - (frame - (rx + rows[0].get_allocated_width()))) <= 1, (tag, "list not centred")
    w.update_config({"mario_game": False, "auto_hide_seconds": 0, "notepad_scale": scale})
    w.show_island(); pump(0.9); w.expand(); pump(0.9)
    for t in ("first task", "second task", "third task"):
        w.entry.set_text(t); w._add(w.entry); pump(0.05)
    centred("fresh")
    w.show_settings_page(); pump(0.5); w.show_notes_page(); pump(0.5)
    centred("after settings")
    w.show_task_detail(next(iter(w._tasks_by_id))); pump(0.5); w.show_notes_page(); pump(0.5)
    centred("after a task detail")
    # hostile page: something that insists on being 900px wide must not stretch the frame
    w.show_settings_page(); pump(0.4)
    w._panel.pack_start(Gtk.Label(label="x" * 150), False, False, 0); w._panel.show_all(); pump(0.4)
    w.show_notes_page(); pump(0.5)
    centred("after an oversized page")
    print("ALIGNED", scale)
""")


@pytest.mark.parametrize("scale", ["0.7", "0.9", "1.2"])
def test_notepad_stays_centred(env, scale):
    e = dict(os.environ, XDG_CONFIG_HOME=str(env / "c"), XDG_STATE_HOME=str(env / "s"), PYTHONPATH=os.getcwd())
    (env / "c" / "nothing-tasks").mkdir(parents=True)
    (env / "c" / "nothing-tasks" / "config.json").write_text(
        '{"vault": "%s", "auto_shortcut": false, "auto_hide_seconds": 0}' % (env / "vault"))
    r = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", SCRIPT, scale], env=e, timeout=120,
                       capture_output=True, text=True, check=False)
    assert "ALIGNED" in r.stdout, r.stdout + r.stderr
