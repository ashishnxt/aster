"""Win+D ("show desktop") must not strand the pill: the first shortcut press brings it back.
Runs against real Mutter inside a virtual display; skipped where the tools are missing."""
import os
import shutil
import subprocess
import textwrap

import pytest

NEEDED = ("mutter", "wmctrl", "xdotool", "xprop", "xwininfo", "xvfb-run", "dbus-run-session")
pytestmark = pytest.mark.skipif(not all(shutil.which(t) for t in NEEDED), reason="needs mutter + X11 tools")

SCRIPT = textwrap.dedent(r"""
    export LIBGL_ALWAYS_SOFTWARE=1 GALLIUM_DRIVER=llvmpipe
    mutter --x11 --sm-disable >/dev/null 2>&1 &
    for i in $(seq 1 30); do sleep 0.5; wmctrl -m >/dev/null 2>&1 && break; done
    cd "$ROOT"
    python3 run.py start; sleep 3
    top() { for i in $(xdotool search --name "^Nothing Tasks$" 2>/dev/null); do
              xprop -id $i WM_STATE 2>/dev/null | grep -q "window state" && { echo $i; break; }; done; }
    shown() {      # echo 1 if the pill is really on screen
      id=$(top); [ -z "$id" ] && { echo 0; return; }
      ms=$(xwininfo -id $id | grep "Map State" | sed 's/.*: //')
      ws=$(xprop -id $id WM_STATE | grep "window state" | sed 's/.*window state: //' | tr -d ' \t')
      hid=$(xprop -id $id _NET_WM_STATE | grep -c HIDDEN)
      [ "$ms" = "IsViewable" ] && [ "$ws" = "Normal" ] && [ "$hid" = "0" ] && echo 1 || echo 0
    }
    wait_for() { for i in $(seq 1 20); do [ "$(shown)" = "$1" ] && { echo $1; return; }; sleep 0.25; done; echo $(shown); }
    python3 run.py toggle;              echo "opened=$(wait_for 1)"
    wmctrl -k on;                       echo "desktop_hides_it=$(wait_for 0)"
    python3 run.py toggle;              echo "first_press_brings_back=$(wait_for 1)"
    sleep 0.6; python3 run.py toggle;   echo "second_press_hides=$(wait_for 0)"
    sleep 0.6; python3 run.py toggle;   echo "third_press_shows=$(wait_for 1)"
    python3 run.py quit
""")


def test_first_press_after_show_desktop_brings_the_pill_back(env):
    root = os.getcwd()
    home = env / "home"
    (home / ".config" / "nothing-tasks").mkdir(parents=True)
    (home / ".config" / "nothing-tasks" / "config.json").write_text(
        '{"vault": "%s", "auto_shortcut": false, "auto_hide_seconds": 0}' % (env / "vault"))
    e = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / ".config"),
             XDG_STATE_HOME=str(home / ".state"), ROOT=root)
    r = subprocess.run(["dbus-run-session", "--", "xvfb-run", "-a", "-s", "-screen 0 1280x800x24 +extension GLX +render",
                        "bash", "-c", SCRIPT], env=e, timeout=150, capture_output=True, text=True, check=False)
    out = r.stdout
    for line in ("opened=1", "desktop_hides_it=0", "first_press_brings_back=1", "second_press_hides=0", "third_press_shows=1"):
        assert line in out, out + r.stderr
