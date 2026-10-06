"""Shortcut registration against a fake `gsettings` (real GNOME is not available in CI)."""
import json
import os
import stat
import textwrap

import pytest

from nothing_tasks import core, system

FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    db = os.environ["FAKE_GS_DB"]
    st = json.load(open(db)) if os.path.exists(db) else {}
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "get":
        k = args[0] + "|" + args[1]
        v = st.get(k)
        if v is None:
            print("@as []" if args[1] == "custom-keybindings" else "''"); sys.exit(0 if args[1] == "custom-keybindings" else 1)
        print(v if args[1] == "custom-keybindings" else repr(v))
    elif cmd == "set":
        st[args[0] + "|" + args[1]] = args[2]
        json.dump(st, open(db, "w"))
    elif cmd == "reset-recursively":
        st = {k: v for k, v in st.items() if not k.startswith(args[0])}
        json.dump(st, open(db, "w"))
''')


@pytest.fixture
def fake_gs(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gs = bindir / "gsettings"
    gs.write_text(FAKE)
    gs.chmod(gs.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GS_DB", str(tmp_path / "gs.json"))
    monkeypatch.setattr(core, "STATE_DIR", tmp_path / "state")
    return tmp_path / "gs.json"


def test_ensure_registers_ctrl_x_once_and_repairs(fake_gs):
    changed, msg = system.ensure_shortcut("<Ctrl>x")
    assert changed and "registered" in msg
    db = json.loads(fake_gs.read_text())
    sch = f"{system.MEDIA_SCHEMA}.custom-keybinding:{system.KEYPATH}"
    assert db[f"{sch}|binding"] == "<Primary>x"                      # GNOME's spelling of Ctrl
    assert db[f"{sch}|command"].endswith("toggle")                   # one key: open AND close
    assert system.KEYPATH in db[f"{system.MEDIA_SCHEMA}|custom-keybindings"]

    assert system.ensure_shortcut("<Ctrl>x")[0] is False             # idempotent
    db[f"{sch}|command"] = "/old/path toggle"                        # stale command gets repaired
    fake_gs.write_text(json.dumps(db))
    assert system.ensure_shortcut("<Ctrl>x")[0] is True
    db = json.loads(fake_gs.read_text())
    assert not db[f"{sch}|command"].startswith("/old")               # really repaired
    db[f"{sch}|binding"] = "<Super>k"                                # user-chosen binding is respected
    fake_gs.write_text(json.dumps(db))
    assert system.ensure_shortcut("<Ctrl>x") == (False, "already registered (<Super>k)")


def test_ensure_never_raises_without_gnome(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    changed, msg = system.ensure_shortcut("<Ctrl>x")
    assert changed is False and "not registered" in msg


def test_remove_shortcut(fake_gs):
    system.set_shortcut("<Ctrl>x")
    system.remove_shortcut()
    assert system.KEYPATH not in json.loads(fake_gs.read_text()).get(f"{system.MEDIA_SCHEMA}|custom-keybindings", "")


def test_ctl_command_resolves_to_an_executable_path():
    cmd = system.ctl_cmd()
    assert os.path.isabs(cmd.split()[0])


def test_changing_the_configured_binding_is_applied(fake_gs):
    sch = f"{system.MEDIA_SCHEMA}.custom-keybinding:{system.KEYPATH}"
    assert system.ensure_shortcut("<Ctrl>x")[0] is True
    changed, msg = system.ensure_shortcut("<alt>x")                  # config changed Ctrl+X -> Alt+X
    assert changed and "registered" in msg
    assert json.loads(fake_gs.read_text())[f"{sch}|binding"] == "<Alt>x"
    assert system.ensure_shortcut("<Alt>x")[0] is False             # and then it is left alone
