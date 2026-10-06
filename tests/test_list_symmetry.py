"""The highlighted / hovered task row must be equally inset on both sides, also with classic
(non-overlay) scrollbars, which used to reserve invisible space on the right."""
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
    w = Island()
    def pump(sec):
        end = time.time() + sec
        while time.time() < end:
            while Gtk.events_pending(): Gtk.main_iteration()
            time.sleep(0.01)
    w.update_config({"mario_game": False})
    w.show_island(); pump(0.9); w.expand(); pump(0.9)
    for i in range(10):
        w.entry.set_text(f"symmetry check task {i}"); w._add(w.entry); pump(0.05)
    w.ex.a = w.ap.a = None; w.ex.v = w.ap.v = 1.0; w._apply(); pump(0.6)
    row = w.list.get_children()[-1]
    x, _ = row.translate_coordinates(w.exp_box, 0, 0)
    left, right = x, w.exp_box.get_allocated_width() - (x + row.get_allocated_width())
    assert abs(left - right) <= 1, (left, right)
    print("SYMMETRIC", left, right)
""")


@pytest.mark.parametrize("overlay", ["1", "0"])
def test_row_is_symmetric(env, overlay):
    e = dict(os.environ, XDG_CONFIG_HOME=str(env / "c"), XDG_STATE_HOME=str(env / "s"),
             GTK_OVERLAY_SCROLLING=overlay, PYTHONPATH=os.getcwd())
    (env / "c" / "nothing-tasks").mkdir(parents=True)
    (env / "c" / "nothing-tasks" / "config.json").write_text(
        '{"vault": "%s", "auto_shortcut": false, "auto_hide_seconds": 0}' % (env / "vault"))
    r = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", SCRIPT], env=e, timeout=90,
                       capture_output=True, text=True, check=False)
    assert "SYMMETRIC" in r.stdout, r.stdout + r.stderr
