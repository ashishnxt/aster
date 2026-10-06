"""Desktop integration: autostart entry and GNOME keyboard shortcut. No GTK."""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import core
from .core import atomic_write, normalize_binding

AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "nothing-tasks.desktop"
MEDIA_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
KEYPATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/nothing-tasks/"


def exec_cmd() -> str:
    return shutil.which("nothing-tasks") or f"{sys.executable} -m nothing_tasks"


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def ctl_cmd() -> str:
    """Absolute path of the fast D-Bus helper (works from a source folder, ~/.local, or the .deb)."""
    for cand in (_root() / "bin" / "nothing-tasks-ctl", Path.home() / ".local/bin/nothing-tasks-ctl",
                 Path("/usr/bin/nothing-tasks-ctl")):
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    found = shutil.which("nothing-tasks-ctl")
    if found:
        return found
    if (_root() / "run.py").is_file():
        return f"{sys.executable} {_root() / 'run.py'}"
    return exec_cmd()


def is_autostart() -> bool:
    return AUTOSTART.exists()


def set_autostart(enabled: bool) -> None:
    if not enabled:
        AUTOSTART.unlink(missing_ok=True)
        return
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text(
        "[Desktop Entry]\nType=Application\nName=Nothing Tasks\n"
        f"Exec={exec_cmd()} start\nNoDisplay=true\nStartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n")


def _gs(*args: str) -> str:
    try:
        return subprocess.run(["gsettings", *args], capture_output=True, text=True,
                              check=True, timeout=5).stdout.strip()
    except FileNotFoundError:
        raise RuntimeError("gsettings not found (not a GNOME desktop?)") from None
    except subprocess.CalledProcessError as e:
        raise RuntimeError("could not read/write GNOME keyboard settings: "
                           + (e.stderr.strip() or "schema not found")) from None


def _norm(binding: str) -> str:
    """GNOME writes <Primary> for Ctrl; normalise common aliases."""
    return normalize_binding(binding).replace("<Ctrl>", "<Primary>")


def check_binding(binding: str) -> str | None:
    """Raise ValueError for a malformed binding; return a warning for risky ones, else None."""
    mods = {m.lower() for m in re.findall(r"<(\w+)>", binding)}
    key = re.sub(r"<\w+>", "", binding).strip()
    if not key:
        raise ValueError("no key given, e.g. <Ctrl>x or <Super>t")
    if not (mods & {"super", "alt", "mod4", "mod1"}) and len(mods) < 2:
        return (f"{binding} also means Cut/Copy in other apps, which will stop working while it is bound "
                "here. Alternatives: <Super>t or <Ctrl><Alt>n.")
    return None


def _current() -> dict | None:
    """Our registered shortcut as {'binding','command'}, or None if not registered."""
    raw = _gs("get", MEDIA_SCHEMA, "custom-keybindings")
    cur = ast.literal_eval(raw[3:].strip() if raw.startswith("@as") else raw)
    if KEYPATH not in cur:
        return None
    s = f"{MEDIA_SCHEMA}.custom-keybinding:{KEYPATH}"
    return {"binding": ast.literal_eval(_gs("get", s, "binding")),
            "command": ast.literal_eval(_gs("get", s, "command"))}


def set_shortcut(binding: str) -> str:
    """Bind `binding` (e.g. '<Ctrl>x') to `toggle`. Returns the command."""
    check_binding(binding)
    command = f"{ctl_cmd()} toggle"
    raw = _gs("get", MEDIA_SCHEMA, "custom-keybindings")
    cur = ast.literal_eval(raw[3:].strip() if raw.startswith("@as") else raw)
    if KEYPATH not in cur:
        cur.append(KEYPATH)
    _gs("set", MEDIA_SCHEMA, "custom-keybindings", str(cur))
    s = f"{MEDIA_SCHEMA}.custom-keybinding:{KEYPATH}"
    _gs("set", s, "name", "Nothing Tasks")
    _gs("set", s, "command", command)
    _gs("set", s, "binding", _norm(binding))
    try:                                                    # remember what the CONFIG asked for (see sync/ensure)
        atomic_write(_applied_file(), json.dumps({"binding": normalize_binding(binding)}))
    except OSError:
        pass
    return command


def _applied_file() -> Path:
    return core.STATE_DIR / "shortcut.json"


def _applied() -> str | None:
    try:
        return json.loads(_applied_file().read_text()).get("binding")
    except (OSError, ValueError):
        return None


def ensure_shortcut(binding: str) -> tuple[bool, str]:
    """Make sure the shortcut exists, points at a working command, and follows the configured
    binding. A binding changed by hand in GNOME Settings is left alone (the config did not change).
    Never raises."""
    try:
        want_binding = normalize_binding(binding)
        cur = _current()
        want = f"{ctl_cmd()} toggle"
        if cur is None or _applied() != want_binding:
            set_shortcut(want_binding)
            atomic_write(_applied_file(), json.dumps({"binding": want_binding}))
            return True, f"registered {want_binding} -> {want}"
        if cur["command"] != want:
            _gs("set", f"{MEDIA_SCHEMA}.custom-keybinding:{KEYPATH}", "command", want)
            return True, f"updated command -> {want}"
        return False, f"already registered ({cur['binding']})"
    except (RuntimeError, ValueError, OSError, SyntaxError) as e:
        return False, f"not registered: {e}"


def sync_shortcut(binding: str) -> tuple[bool, str]:
    """For when auto-registration is OFF. If a shortcut was registered earlier (by an older version, or by
    pressing Apply) it must still follow the configured key; otherwise the old key keeps opening the pill
    while Settings shows another one. Registers nothing new. A key changed by hand in GNOME Settings is
    left alone (the config did not change). Never raises."""
    try:
        cur = _current()
        if cur is None:
            return False, "no shortcut registered (auto-register is off)"
        want = normalize_binding(binding)
        if _applied() != want:
            set_shortcut(want)
            return True, f"switched GNOME's shortcut {cur['binding']} -> {want}"
        return False, f"GNOME shortcut left as it is ({cur['binding']})"
    except (RuntimeError, ValueError, OSError, SyntaxError) as e:
        return False, f"shortcut not synced: {e}"


def remove_shortcut() -> None:
    raw = _gs("get", MEDIA_SCHEMA, "custom-keybindings")
    cur = ast.literal_eval(raw[3:].strip() if raw.startswith("@as") else raw)
    if KEYPATH in cur:
        cur.remove(KEYPATH)
        _gs("set", MEDIA_SCHEMA, "custom-keybindings", str(cur))
    subprocess.run(["gsettings", "reset-recursively",
                    f"{MEDIA_SCHEMA}.custom-keybinding:{KEYPATH}"], capture_output=True, timeout=5, check=False)
