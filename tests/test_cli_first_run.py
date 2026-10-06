"""The very first command on a fresh machine must start the widget in the background,
return promptly, and later commands must reach it - the bug a user hit."""
import os
import shutil
import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(not (shutil.which("xvfb-run") and shutil.which("dbus-run-session")),
                                reason="needs xvfb-run and dbus-run-session")

SCRIPT = textwrap.dedent("""
    set -e
    R="$1"
    timeout 30 python3 "$R/run.py" toggle                 # first ever command
    python3 "$R/run.py" toggle                            # reaches the running widget
    timeout 5 sh "$R/bin/nothing-tasks-ctl" hide          # shortcut helper
    python3 "$R/run.py" status | grep -q running
    python3 "$R/run.py" quit
    sleep 1
    python3 "$R/run.py" quit | grep -q "not running"
    echo FIRST_RUN_OK
""")


def test_first_command_starts_background_widget(env):
    root = os.path.dirname(os.path.dirname(__file__))
    e = dict(os.environ, XDG_CONFIG_HOME=str(env / "c"), XDG_STATE_HOME=str(env / "s"),
             PYTHONPATH=root)
    (env / "c" / "nothing-tasks").mkdir(parents=True)
    (env / "c" / "nothing-tasks" / "config.json").write_text('{"vault": "%s"}' % (env / "vault"))
    r = subprocess.run(["dbus-run-session", "--", "xvfb-run", "-a", "bash", "-c", SCRIPT, "_", root],
                       env=e, timeout=90, capture_output=True, text=True, check=False)
    assert "FIRST_RUN_OK" in r.stdout, r.stdout + r.stderr


def test_shortcut_validation():
    from nothing_tasks.system import check_binding
    assert check_binding("<Ctrl>x") and "Cut" in check_binding("<Ctrl>x")      # allowed, but warned
    assert check_binding("<Super>t") is None and check_binding("<Ctrl><Alt>n") is None
    for bad in ("", "<Ctrl>", "<Super>"):
        with pytest.raises(ValueError):
            check_binding(bad)
    assert sys.version_info >= (3, 10)
