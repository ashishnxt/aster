"""Command line entry point. Heavy GTK code is only imported when the app must start."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__

APP_ID, OBJ_PATH = "dev.nothing.tasks", "/dev/nothing/tasks"
APP_COMMANDS = ("toggle", "show", "hide", "expand", "collapse", "focus", "settings", "start", "quit")

USAGE = f"""nothing-tasks {__version__} - Dynamic-Island stopwatch + Obsidian tasks

usage: nothing-tasks [command]

widget:
  toggle (default)   show the pill, or hide it if it is visible
  show | hide        explicit, idempotent
  expand | collapse  open / close the notepad
  focus              bring the pill to the front and give it keyboard focus
  settings           open the settings window
  start              run in the background without showing anything
  quit               stop the background process
  debug              run in the foreground with verbose logging (for troubleshooting)

info & setup:
  status             print timer state as JSON (works without the widget running)
  doctor             check the environment and print diagnostics
  install-shortcut [KEY]   bind a GNOME shortcut to toggle (default <Ctrl>x; the widget also does this by itself)
  remove-shortcut
  autostart on|off   start silently at login
  --version, --help

MCP server for AI assistants:  nothing-tasks-mcp
"""


def _dbus_action(name: str) -> bool:
    """Trigger a running instance over D-Bus without importing GTK (~50 ms)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        # GNOME hands a shortcut-launched command a startup/activation token; passing it on is what
        # lets the pill take keyboard focus (otherwise focus-stealing prevention may refuse it).
        platform = {}
        for env, key in (("DESKTOP_STARTUP_ID", "desktop-startup-id"), ("XDG_ACTIVATION_TOKEN", "activation-token")):
            if os.environ.get(env):
                platform[key] = GLib.Variant("s", os.environ[env])
        bus.call_sync(APP_ID, OBJ_PATH, "org.freedesktop.Application", "ActivateAction",
                      GLib.Variant("(sava{sv})", (name, [], platform)), None,
                      Gio.DBusCallFlags.NO_AUTO_START, 1500, None)
        return True
    except Exception:  # noqa: BLE001 - not running / no bus
        return False


def _spawn_background():
    """Start the widget detached from this terminal; its output goes to startup.log."""
    from .core import STATE_DIR
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    root = str(Path(__file__).resolve().parent.parent)
    code = f"import sys; sys.path.insert(0, {root!r}); from nothing_tasks.cli import main; sys.exit(main(['_run']))"
    out = open(STATE_DIR / "startup.log", "ab")           # noqa: SIM115 - handed to the child
    return subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.DEVNULL, stdout=out,
                            stderr=out, start_new_session=True)


def _wait_ready(proc, timeout=8.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _dbus_action("start"):
            return True
        if proc.poll() is not None:          # it died during start-up
            return False
        time.sleep(0.1)
    return False


def _log_tail(n=12) -> str:
    from .core import LOG_FILE, STATE_DIR
    out = []
    for f in (STATE_DIR / "startup.log", LOG_FILE):
        try:
            out.append(f"--- {f} ---\n" + "\n".join(f.read_text(errors="replace").splitlines()[-n:]))
        except OSError:
            pass
    return "\n".join(out) or "(no log yet)"


def _run_foreground(cmd: str) -> int:
    # The pill must sit at the exact top-centre. Wayland forbids apps from placing their
    # own windows, so on a Wayland session we run through XWayland.
    if os.environ.get("DISPLAY") and not os.environ.get("NT_NATIVE_WAYLAND"):
        os.environ.setdefault("GDK_BACKEND", "x11")
    from .ui import main as run_app
    return run_app([cmd])


def doctor() -> int:
    from . import system
    from .core import CONFIG_FILE, LOG_FILE, VaultError, VaultStore, load_config
    ok = True

    def line(good, msg):
        nonlocal ok
        ok &= good
        print(("  ok   " if good else "  FAIL ") + msg)

    print(f"nothing-tasks {__version__}  python {platform.python_version()}")
    line(sys.version_info >= (3, 10), "Python >= 3.10")
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        import cairo  # noqa: F401
        from gi.repository import Gtk  # noqa: F401
        line(True, "GTK 3 + PyGObject + pycairo")
    except Exception as e:  # noqa: BLE001
        line(False, f"GTK 3 / PyGObject missing: {e}  (sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-3.0)")
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    print(f"  info session type: {session}" + (" (runs via XWayland so it can position itself)" if session == "wayland" else ""))
    line(bool(os.environ.get("DISPLAY")) or session != "wayland", "X11/XWayland display available (DISPLAY set)")
    cfg = load_config()
    print(f"  info config: {CONFIG_FILE}")
    try:
        store = VaultStore(cfg["vault"], cfg["note"])
        line(os.path.isdir(os.path.expanduser(cfg["vault"])), f"vault folder exists: {cfg['vault']}")
        parent = store.path.parent
        line(os.access(parent if parent.exists() else os.path.expanduser(cfg["vault"]), os.W_OK), f"vault writable ({store.path.name})")
    except VaultError as e:
        line(False, str(e))
    line(bool(shutil.which("gdbus")), "gdbus (fast shortcut path)")
    print("  info widget running: " + ("yes" if _dbus_action("start") else "no"))
    try:
        cur = system._current()
        print("  info shortcut: " + (f"{cur['binding']} -> {cur['command']}" if cur else "not registered"))
    except (RuntimeError, ValueError, SyntaxError) as e:
        print(f"  info shortcut: cannot read GNOME settings ({e})")
    print(f"  info autostart: {'on' if system.is_autostart() else 'off'}   log: {LOG_FILE}")
    print("  info recent log:\n" + "\n".join("    " + ln for ln in _log_tail(6).splitlines()))
    try:
        import mcp  # noqa: F401
        line(True, "MCP SDK installed (nothing-tasks-mcp)")
    except ImportError:
        print("  info MCP SDK not installed (pip install 'mcp>=1.2') - only needed for AI assistants")
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "toggle"

    if cmd in ("-h", "--help", "help"):
        print(USAGE)
        return 0
    if cmd in ("-V", "--version", "version"):
        print(__version__)
        return 0
    if cmd == "doctor":
        return doctor()
    if cmd == "status":
        from .core import Stopwatch
        print(json.dumps(Stopwatch().snapshot()))
        return 0
    if cmd in ("install-shortcut", "remove-shortcut", "autostart"):
        from . import system
        try:
            if cmd == "install-shortcut":
                from .core import DEFAULT_CONFIG
                key = argv[1] if len(argv) > 1 else DEFAULT_CONFIG["shortcut"]
                warn = system.check_binding(key)
                print(f"Bound {key} -> {system.set_shortcut(key)} toggle")
                if warn:
                    print("warning: " + warn)
            elif cmd == "remove-shortcut":
                system.remove_shortcut()
                print("Shortcut removed")
            else:
                on = (argv[1:2] or [""])[0] == "on"
                if (argv[1:2] or [""])[0] not in ("on", "off"):
                    print("usage: nothing-tasks autostart on|off")
                    return 2
                system.set_autostart(on)
                print(f"Autostart {'enabled' if on else 'disabled'}")
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0
    if cmd not in APP_COMMANDS and cmd not in ("debug", "_run"):
        print(f"nothing-tasks: unknown command '{cmd}'\n\n{USAGE}", file=sys.stderr)
        return 2

    if cmd == "_run":                             # internal: the background process
        return _run_foreground("start")
    if cmd == "debug":
        if _dbus_action("start"):
            print("The widget is already running. Stop it first:  nothing-tasks quit", file=sys.stderr)
            return 1
        os.environ["NT_DEBUG"] = "1"
        print("Running in the foreground with debug logging. Ctrl+C to stop.", file=sys.stderr)
        return _run_foreground("show")

    if _dbus_action(cmd):                         # already running: fast path, no GTK import
        if cmd == "start":
            print("Nothing Tasks is already running.")
        return 0
    if cmd == "quit":
        print("Nothing Tasks is not running.")
        return 0
    proc = _spawn_background()                    # first use: start it in the background
    if not _wait_ready(proc):
        print("Nothing Tasks could not start. Run `nothing-tasks doctor`, or "
              "`nothing-tasks debug` to see the error.\n" + _log_tail(), file=sys.stderr)
        return 1
    if sys.stderr.isatty():
        print("Nothing Tasks started in the background.", file=sys.stderr)
    if cmd != "start" and not _dbus_action(cmd):
        print(f"Started, but could not send '{cmd}'. See `nothing-tasks doctor`.", file=sys.stderr)
        return 1
    return 0
