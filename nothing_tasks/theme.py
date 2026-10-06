"""Light/dark palettes and the system colour-scheme lookup."""
from __future__ import annotations

import logging

log = logging.getLogger("nothing_tasks")

PALETTES = {
    "dark": {"bg": "#161616", "surface": "#212121", "line": "#3A3A3A",
             "muted": "#7A7A7A", "text": "#E8E8E8", "dim": "#2A2A2A"},
    "light": {"bg": "#F4F4F6", "surface": "#E6E6EA", "line": "#C9C9D0",
              "muted": "#6B6B75", "text": "#1B1B1F", "dim": "#D6D6DD"},
}


def _iface():
    try:
        from gi.repository import Gio
        src = Gio.SettingsSchemaSource.get_default()
        if src and src.lookup("org.gnome.desktop.interface", True):
            return Gio.Settings.new("org.gnome.desktop.interface")
    except Exception as e:  # noqa: BLE001 - no GNOME settings: treat as dark
        log.debug("no system theme info: %s", e)
    return None


def system_prefers_dark() -> bool:
    s = _iface()
    if s is None:
        return True
    try:
        has_scheme = s.props.settings_schema.has_key("color-scheme")      # GNOME 42+
        scheme = s.get_string("color-scheme") if has_scheme else ""
    except Exception:  # noqa: BLE001
        scheme = ""
    if scheme == "prefer-dark":
        return True
    if scheme == "prefer-light":
        return False
    return "dark" in s.get_string("gtk-theme").lower()      # 'default': decide by the GTK theme name


def resolve(mode: str) -> str:
    """'auto' follows the system; returns 'dark' or 'light'."""
    if mode in ("dark", "light"):
        return mode
    return "dark" if system_prefers_dark() else "light"


def watch(callback):
    """Call `callback()` when the system light/dark setting changes. Returns the Gio.Settings or None."""
    s = _iface()
    if s is not None:
        s.connect("changed::color-scheme", lambda *_: callback())
        s.connect("changed::gtk-theme", lambda *_: callback())
    return s
