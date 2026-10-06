"""Dynamic-Island style pill: dot-matrix stopwatch that morphs into a task notepad.

States:  hidden -> compact (pill, stopwatch) -> expanded (notepad | settings page)
Keys:    pill:     Space = notepad   Enter = start/pause   Esc = hide
         notepad:  type + Enter = add task   Esc = back to pill   Ctrl+, = settings
         settings: Esc = back to the notepad
"""
from __future__ import annotations

import logging
import math
import os
import signal
import sys
import threading
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk

from . import APP_NAME, __version__, system, theme
from .core import (
    Stopwatch,
    VaultError,
    VaultStore,
    fmt_hms,
    load_config,
    sanitize_config,
    save_config,
    setup_logging,
)
from .detail import TaskDetail
from .game import MarioGame
from .settings import SettingsPanel

log = logging.getLogger("nothing_tasks")

# live-editable from Settings: accent/border/input border, light-dark palette, glass
PAL = {"accent": "#D71921", "border": "#D71921", "ibw": 1, "iscale": 0.85, "dark": True, "glass": True, "glass_alpha": 0.62,
       **theme.PALETTES["dark"]}

NOTE_W, NOTE_H = 440, 500    # expanded notepad at notepad_scale 1.0
BASE_CW, BASE_CH = 216, 44   # compact pill at scale 1.0
MAX_TOP = 80                 # largest allowed top_margin
MAX_ROWS = 200               # newest tasks shown in the notepad (the note itself keeps everything)
EXP_RADIUS = 34

CSS = """
window { background: transparent; }
* { font-family: "Space Mono", "JetBrains Mono", "DejaVu Sans Mono", monospace; }
.xcard { padding: 14px 14px 16px 14px; }
.tiny { color: @MUTED@; font-size: 10pt; }
.err { color: @ACCENT@; }
.pill { background: none; border: 1px solid @LINE@; border-radius: 999px; color: @TEXT@;
        padding: 6px 24px; font-size: 10pt; box-shadow: none; text-shadow: none; }
.pill:hover { border-color: @MUTED@; }
.pill.go { background: @ACCENT@; border-color: @ACCENT@; color: white; }
.flat { background: none; border: none; box-shadow: none; padding: 0 4px; color: @MUTED@;
        min-height: 0; min-width: 0; text-shadow: none; }
.flat:hover { color: @TEXT@; }
.flat.big { min-width: 34px; min-height: 34px; font-size: 15pt; border-radius: 17px; padding: 0 4px; }
.flat.big:hover { background: @SURFACE@; }
.flat.hdr { min-width: 48px; min-height: 48px; font-size: 24pt; border-radius: 24px; padding: 0 4px; }
.flat.hdr:hover { background: @SURFACE@; }
.flat.txt { font-size: 10pt; }
button.flat.backbtn { border: 1px solid @MUTED@; border-radius: 999px; padding: 6px 18px; margin: 3px 3px 3px 2px;
                min-height: 0; min-width: 0; font-size: 10pt; }
button.flat.backbtn:hover { background: @SURFACE@; border-color: @TEXT@; }
.del:hover, .undo { color: @ACCENT@; }
.dot-on { color: @ACCENT@; }
list, row, scrolledwindow, viewport { background: transparent; }
row { border-radius: 16px; padding: 3px 6px; }
row:hover { background: @SURFACE@; }
row.newrow { background: @SOFT@; }
.task { color: @MUTED@; font-size: 12pt; }
.task.active { color: @TEXT@; }
.time { color: @MUTED@; font-size: 9pt; }
entry.addtask { background: @SURFACE@; color: @TEXT@; border: @IBW@px solid @BORDER@; border-radius: 999px;
                padding: @IPADV@px @IPADH@px; min-height: @IMINH@px; font-size: @IFONT@pt; caret-color: @BORDER@;
                box-shadow: none; text-shadow: none; }
entry.addtask:focus { box-shadow: 0 0 0 3px @BSOFT@; }
scrollbar { opacity: 0; }

.spanel label { color: @TEXT@; font-size: 10pt; }
.spanel .heading { color: @ACCENT@; font-size: 9pt; margin-top: 12px; }
.spanel .hint { color: @MUTED@; font-size: 9pt; }
.dpanel label.detailtext { color: @TEXT@; font-size: 13pt; }
.dpanel label.chip { color: @MUTED@; border: 1px solid @LINE@; border-radius: 999px; padding: 2px 12px; font-size: 9pt; }
.dpanel label.chip.done { color: @ACCENT@; border-color: @ACCENT@; }
.dpanel button.pill { padding: 8px 10px; }
.dpanel button.danger:hover { border-color: @ACCENT@; color: @ACCENT@; }
.spanel .warn { color: @ACCENT@; font-size: 9pt; }
.spanel .devcard { background: @SURFACE@; border: 1px solid @LINE@; border-radius: 22px; padding: 18px; }
.spanel label.appmark { color: @ACCENT@; font-size: 16pt; }
.spanel label.appname { color: @TEXT@; font-size: 15pt; }
.spanel label.verbadge { color: @ACCENT@; background: @SOFT@; border-radius: 999px; padding: 2px 12px; font-size: 9pt; }
.spanel label.avatar { background: @ACCENT@; color: white; border-radius: 999px; font-size: 20pt; }
.spanel label.devname { color: @TEXT@; font-size: 13pt; }
.spanel button.devrow { background: none; border: none; border-radius: 12px; padding: 8px 10px; }
.spanel button.devrow:hover { background: @SOFT@; }
.spanel button.devrow label { color: @TEXT@; font-size: 10pt; }
.spanel button.pillbtn { background: none; border: 1px solid @LINE@; border-radius: 999px; padding: 3px 0; font-size: 9pt; min-height: 0; }
.spanel button.pillbtn:hover { border-color: @ACCENT@; }
.spanel .back { font-size: 11pt; }
.spanel switch:checked { background: @ACCENT@; }
.spanel scale highlight { background: @ACCENT@; }
.spanel scale slider:hover { background: @ACCENT@; }
.spanel button, .spanel combobox button { background: @SURFACE@; background-image: none; color: @TEXT@;
        border: 1px solid @LINE@; border-radius: 10px; box-shadow: none; text-shadow: none; min-height: 30px; }
.spanel button:hover { border-color: @ACCENT@; }
.spanel button label { color: @TEXT@; }
.spanel spinbutton, .spanel spinbutton button { background: @SURFACE@; background-image: none; color: @TEXT@;
        border-color: @LINE@; }
.spanel switch { background: @SURFACE@; border: 1px solid @LINE@; }
.spanel .flat { background: none; border: none; }
.spanel entry { background: @SURFACE@; color: @TEXT@; border: 1px solid @LINE@; border-radius: 10px;
                padding: 6px 10px; box-shadow: none; caret-color: @ACCENT@; }
.spanel entry:focus { border-color: @ACCENT@; }
"""

GLYPHS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["0", "0", "1", "0", "1", "0", "0"],
}


def build_css() -> bytes:
    r, g, b = (int(PAL["accent"][i:i + 2], 16) for i in (1, 3, 5))
    css = CSS
    br, bg_, bb = (int(PAL["border"][i:i + 2], 16) for i in (1, 3, 5))     # the input follows the border colour
    sc = PAL["iscale"]
    iminh = round(22 * sc)
    ipv = max(2, (round(50 * sc) - 2 * PAL["ibw"] - iminh) // 2)           # box height stays steady
    sr, sg, sb = (int(PAL["surface"][i:i + 2], 16) for i in (1, 3, 5))
    surface = f"rgba({sr},{sg},{sb},0.62)" if PAL["glass"] else PAL["surface"]
    for k, v in (("@ACCENT@", PAL["accent"]), ("@SOFT@", f"rgba({r},{g},{b},0.20)"), ("@SURFACE@", surface),
                 ("@LINE@", PAL["line"]), ("@MUTED@", PAL["muted"]), ("@TEXT@", PAL["text"]),
                 ("@BORDER@", PAL["border"]), ("@BSOFT@", f"rgba({br},{bg_},{bb},0.20)"),
                 ("@IBW@", str(PAL["ibw"])), ("@IPADV@", str(ipv)), ("@IPADH@", str(round(22 * sc))),
                 ("@IMINH@", str(iminh)), ("@IFONT@", f"{12 * sc:.1f}")):
        css = css.replace(k, v)
    return css.encode()


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def clamp01(v):
    return min(1.0, max(0.0, v))


def rounded_rect(cr, x, y, w, h, r):
    r = max(0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


# ------------------------------------------------------------------ easing
def spring(decay, freq):
    """Damped spring: overshoots, rings once, settles (the iPhone feel)."""
    return lambda p: 1 - math.exp(-decay * p) * math.cos(freq * p)


ease_appear = spring(7.0, 10.0)      # ~11% overshoot
ease_expand = spring(8.0, 9.0)       # ~6% overshoot


def ease_out_cubic(p):
    return 1 - (1 - p) ** 3


def ease_in_cubic(p):
    return p ** 3


class Tween:
    def __init__(self, value):
        self.v, self.a = value, None

    def go(self, to, dur, ease, done=None):
        self.a = (self.v, to, time.monotonic(), max(dur, 0.001), ease, done)

    def step(self, now):
        if not self.a:
            return False
        f, t, t0, d, e, done = self.a
        p = min(1.0, (now - t0) / d)
        self.v = f + (t - f) * e(p)
        if p >= 1:
            self.a, self.v = None, t
            if done:
                done()
        return True


# ------------------------------------------------------------------ dot display
class DotDisplay(Gtk.DrawingArea):
    """Dot-matrix HH:MM:SS. Full size can add a 60-dot seconds strip."""

    def __init__(self, width, height, compact=False):
        super().__init__()
        self.set_size_request(width, height)
        self.compact, self.strip = compact, True
        self.text, self.live, self.seconds = "00:00:00", False, 0
        self.connect("draw", self._draw)

    def update(self, seconds: float, live: bool):
        text = fmt_hms(seconds)
        if text != self.text or live != self.live:
            self.text, self.live, self.seconds = text, live, int(seconds) % 60
            self.queue_draw()

    def _draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cols = sum(len(GLYPHS[c][0]) for c in self.text) + len(self.text) - 1
        pitch = w / cols
        r = pitch * 0.36
        oy = (h - 7 * pitch) / 2 if self.compact else 0
        on, off = rgb(PAL["accent"] if self.live else PAL["text"]), rgb(PAL["dim"])
        blink_off = self.live and self.seconds % 2 == 1        # ":" blinks while running
        x = 0.0
        for ch in self.text:
            g = GLYPHS[ch]
            for row, bits in enumerate(g):
                for col, bit in enumerate(bits):
                    lit = bit == "1" and not (ch == ":" and blink_off)
                    cr.set_source_rgb(*(on if lit else off))
                    cr.arc((x + col + 0.5) * pitch, oy + (row + 0.5) * pitch, r, 0, 2 * math.pi)
                    cr.fill()
            x += len(g[0]) + 1
        if not self.compact and self.strip:
            y, step = 7 * pitch + 18, w / 60
            for i in range(60):
                lit = self.seconds > 0 and i < self.seconds
                cr.set_source_rgb(*(rgb(PAL["accent"]) if lit else off))
                cr.arc((i + 0.5) * step, y, 1.8, 0, 2 * math.pi)
                cr.fill()


# ------------------------------------------------------------------ the island
class Island(Gtk.Window):
    def __init__(self):
        super().__init__(title=APP_NAME)
        self.cfg = load_config()
        debug = bool(os.environ.get("NT_DEBUG"))
        setup_logging("DEBUG" if debug else self.cfg["log_level"], console=debug or sys.stderr.isatty())
        self.state = "hidden"
        self._page = "notes"                 # notes | settings | detail
        self._panel = None
        self._detail = None
        self._detail_id = None
        self._tasks_by_id = {}
        self._was_active = self._hover = False
        self._anim_id = self._debounce = self._toast_id = 0
        self._toast_on = False
        self._last_toggle = 0.0
        self._last_input = time.monotonic()
        self._undo = None
        self._hl_row = None
        self._hl_task, self._hl_until = None, 0.0
        self._render_key = None
        self._bg_key_cached, self._bg_surf = None, None
        self._mon = None
        self.ex, self.ap = Tween(0.0), Tween(0.0)   # expansion / appear progress
        self.alpha = 0.0
        self._backdrop = None
        self._win_pos = (0, 0)
        self.top = self.cfg["top_margin"]
        self._dims()
        self.geo = (0, 0, BASE_CW, BASE_CH, BASE_CH / 2)
        self.sw = Stopwatch()
        self.store = None

        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_resizable(False)
        self.set_size_request(self.win_w, self.win_h)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)        # no dock / alt-tab entry
        self.set_skip_pager_hint(True)
        self.set_role("nothing-tasks-pill")
        self.stick()
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("draw", self._draw_bg)
        self.connect("key-press-event", self._on_key)
        self.connect("notify::is-active", self._on_active)
        self.connect("enter-notify-event", lambda *_: self._set_hover(True))
        self.connect("leave-notify-event", lambda *_: self._set_hover(False))
        self.connect("motion-notify-event", lambda *_: self._bump())
        self.connect("delete-event", lambda *_: self.hide_island() or True)

        self._css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self._css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._build()
        self._apply_cfg()
        self._theme_watch = theme.watch(self._on_system_theme)       # follow the system light/dark switch
        self._tick_id = self._ah_id = 0               # timers exist only while the pill is on screen
        GLib.timeout_add(1200, self._ensure_shortcut)

    # -------------------------------------------------------- config
    def _dims(self):
        s = self.cfg["pill_scale"]
        self.cw, self.ch = int(BASE_CW * s), int(BASE_CH * s)
        self.dot_w, self.dot_h = int(130 * s), int(24 * s)
        n = self.cfg["notepad_scale"]
        self.ew, self.eh = int(NOTE_W * n), int(NOTE_H * n)
        self.dh = int(7 * (self.ew - 52) / 39) + 24                 # exactly what the dots + strip need
        self.win_w = int(self.ew * 1.1) + 30                        # room for the spring overshoot
        self.win_h = MAX_TOP + int(self.eh * 1.1) + 10

    def _on_system_theme(self):
        if self.cfg["theme"] == "auto":
            self._apply_cfg()

    @property
    def in_settings(self):
        return self.state == "expanded" and self._page == "settings"

    @property
    def in_subpage(self):
        """Settings or a task's detail: don't auto-hide or fold away while someone is reading."""
        return self.state == "expanded" and self._page in ("settings", "detail")

    def update_config(self, changes: dict):
        """Called by the settings page: validate, persist, apply live."""
        self.cfg = sanitize_config({**self.cfg, **changes})
        try:
            save_config(self.cfg)
        except OSError as e:
            self._toast(f"CANNOT SAVE SETTINGS: {e.strerror}", error=True)
        self._apply_cfg()

    def _apply_cfg(self):
        c = self.cfg
        PAL["accent"], PAL["border"], PAL["ibw"] = c["accent"], c["border_color"], c["input_border_width"]
        PAL["iscale"] = c["input_scale"]
        mode = theme.resolve(c["theme"])                            # auto -> follows the system
        PAL.update(theme.PALETTES[mode])
        PAL["dark"] = mode == "dark"
        PAL["glass"] = c["glass"]
        PAL["glass_alpha"] = 0.94 - 0.58 * c["glass_strength"] / 100
        Gtk.Settings.get_default().set_property("gtk-application-prefer-dark-theme", PAL["dark"])
        self._css.load_from_data(build_css())
        if not os.environ.get("NT_DEBUG"):
            log.setLevel(c["log_level"])
        self._dims()
        self.cmp_box.set_size_request(self.cw, self.ch)
        self.cmp_time.set_size_request(self.dot_w, self.dot_h)
        self.game.configure(self.cw, self.ch)
        self.exp_box.set_size_request(self.ew, self.eh)
        self.display.set_size_request(self.ew - 52, self.dh)
        self._size_input()
        self.set_size_request(self.win_w, self.win_h)
        if self.state != "hidden":
            self._place()
        self.display.strip = c["show_seconds_strip"]
        self.stack.set_transition_duration(int(self._dur(0.18) * 1000))
        try:
            store = VaultStore(c["vault"], c["note"])
        except VaultError as e:
            self._toast(str(e).upper(), error=True)
            store = self.store or VaultStore(str(GLib.get_home_dir()), "Widget Tasks.md")
        if not self.store or store.path != self.store.path:
            self.store = store
            self._render_key = None
            self._watch_vault()
            if self.state != "hidden":
                self.refresh_tasks()
        self.top = c["top_margin"]
        if self.state != "hidden":
            self._start_timers()                      # e.g. auto-hide was just switched on in Settings
        self._update_compact_mode()
        self._apply()
        self.display.queue_draw()
        self.cmp_time.queue_draw()
        self.queue_draw()

    def _size_input(self):
        """The Add-a-task box is exactly as wide as the task list, so it lines up with the highlighted
        row; input_width (%) makes it narrower, centred."""
        list_w = self.ew - 28                                       # notepad width minus the card padding (2 x 14)
        margin = int(list_w * (100 - self.cfg["input_width"]) / 200)
        self.entry.set_margin_start(margin)
        self.entry.set_margin_end(margin)

    def _dur(self, seconds):
        return seconds / self.cfg["animation_speed"] if self.cfg["animations"] else 0.001

    def _watch_vault(self):
        if self._mon:
            self._mon.cancel()
            self._mon = None
        try:
            self.store.path.parent.mkdir(parents=True, exist_ok=True)
            self._mon = Gio.File.new_for_path(str(self.store.path.parent)).monitor_directory(
                Gio.FileMonitorFlags.NONE, None)
            self._mon.connect("changed", self._on_vault_changed)
        except (OSError, GLib.Error) as e:
            log.warning("cannot watch vault: %s", e)

    def _ensure_shortcut(self):
        """Keep GNOME's shortcut in line with the configured one (once, in a thread: gsettings is slow).
        auto_shortcut ON: register / repair it. OFF: register nothing new, but an existing registration
        (e.g. the old Ctrl+X) is switched to the configured key so the two never disagree."""
        def work():
            fn = system.ensure_shortcut if self.cfg["auto_shortcut"] else system.sync_shortcut
            _changed, msg = fn(self.cfg["shortcut"])
            log.info("shortcut: %s", msg)
        threading.Thread(target=work, daemon=True).start()
        return False

    # -------------------------------------------------------- layout
    def _build(self):
        self.fixed = Gtk.Fixed()
        self.add(self.fixed)

        # compact pill content: status dot + small dot-matrix time
        self.cmp_box = Gtk.EventBox()
        self.cmp_box.set_visible_window(False)
        self.cmp_box.set_tooltip_text("Space: notepad   Enter: start/pause   Esc: hide")
        row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.cmp_dot = Gtk.Label()
        self.cmp_time = DotDisplay(self.dot_w, self.dot_h, compact=True)
        row.pack_start(self.cmp_dot, False, False, 0)
        row.pack_start(self.cmp_time, False, False, 0)
        self.game = MarioGame(lambda: (self.cfg["game_theme"], PAL, PAL["glass"]))
        self.game.configure(self.cw, self.ch)
        self.cmp_stack = Gtk.Stack()                      # digits while timing, the game while idle
        self.cmp_stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.cmp_stack.add_named(row, "time")
        self.cmp_stack.add_named(self.game, "game")
        row.show_all()
        self.game.show()
        self.cmp_box.add(self.cmp_stack)
        self.cmp_box.connect("button-press-event", self._on_pill_click)
        self.cmp_box.set_size_request(self.cw, self.ch)
        self.fixed.put(self.cmp_box, (self.win_w - self.cw) // 2, MAX_TOP)

        # expanded: a stack with the notepad page and (lazily) the settings page
        self.exp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.exp_box.get_style_context().add_class("xcard")
        self.exp_box.set_size_request(self.ew, self.eh)
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_hhomogeneous(False)          # each page is sized on its own: a wide page can't stretch the others
        clip = Gtk.ScrolledWindow()               # guard: no page can ever widen the notepad frame again
        clip.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.EXTERNAL)
        clip.set_shadow_type(Gtk.ShadowType.NONE)
        clip.add(self.stack)
        self.exp_box.pack_start(clip, True, True, 0)

        notes = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        head = Gtk.Box(spacing=2)
        head.set_margin_start(12)
        head.set_margin_end(12)
        self.head_lbl = Gtk.Label(xalign=0)
        self.head_lbl.get_style_context().add_class("tiny")
        self.status_lbl = Gtk.Label(xalign=1, ellipsize=3)
        self.status_lbl.get_style_context().add_class("tiny")
        self.undo_btn = self._flat("UNDO", self._undo_delete, "undo", "txt")
        self.undo_btn.set_no_show_all(True)
        gear = self._flat("⚙", lambda *_: self._toggle_settings(), "hdr")
        gear.set_tooltip_text("Settings (Ctrl+S)")
        close = self._flat("✕", lambda *_: self.hide_island(), "hdr")
        close.set_tooltip_text("Hide")
        head.pack_start(self.head_lbl, False, False, 0)
        head.pack_start(self.status_lbl, True, True, 8)
        head.pack_end(close, False, False, 0)
        head.pack_end(gear, False, False, 0)
        head.pack_end(self.undo_btn, False, False, 0)
        notes.pack_start(head, False, False, 0)

        self.display = DotDisplay(self.ew - 52, self.dh)
        self.display.set_margin_start(12)
        self.display.set_margin_end(12)
        notes.pack_start(self.display, False, False, 0)

        btns = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
        self.go = Gtk.Button(label="START")
        self.go.get_style_context().add_class("pill")
        self.go.set_can_focus(False)
        self.go.connect("clicked", self._toggle)
        reset = Gtk.Button(label="RESET")
        reset.get_style_context().add_class("pill")
        reset.set_can_focus(False)
        reset.connect("clicked", self._reset)
        btns.pack_start(self.go, False, False, 0)
        btns.pack_start(reset, False, False, 0)
        notes.pack_start(btns, False, False, 2)

        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.connect("row-activated", self._on_row_activated)       # click a task -> its full text
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)   # wheel scrolls, no bar
        self.scroller.set_overlay_scrolling(True)
        self.scroller.add(self.list)
        notes.pack_start(self.scroller, True, True, 0)

        self.entry = Gtk.Entry(placeholder_text="＋  Add a task…", max_length=500)
        self.entry.get_style_context().add_class("addtask")
        self.entry.connect("activate", self._add)
        notes.pack_start(self.entry, False, False, 2)          # its width is set by _size_input()

        self.stack.add_named(notes, "notes")
        self.fixed.put(self.exp_box, (self.win_w - self.ew) // 2, MAX_TOP)

    @staticmethod
    def _flat(label, cb, *classes):
        b = Gtk.Button(label=label)
        b.set_can_focus(False)
        ctx = b.get_style_context()
        for c in ("flat", *classes):
            ctx.add_class(c)
        b.connect("clicked", cb)
        return b

    # -------------------------------------------------------- drawing / geometry
    def _bg_key(self):
        x, y, w, h, r = self.geo
        return (round(x, 1), round(y, 1), round(w, 1), round(h, 1), round(r, 1), round(self.alpha, 3),
                round(self.ex.v, 3), self.cfg["border_width"], PAL["bg"], PAL["border"], PAL["glass"],
                round(PAL["glass_alpha"], 3), PAL["dark"], id(self._backdrop), self.win_w, self.win_h)

    def _draw_bg(self, _w, cr):
        """The island's glass + outline. While it is animating it is painted directly; once it is
        still (the game running, the timer counting) it is a single cached blit instead of
        gradients and strokes on every frame."""
        if self._anim_id:
            self._paint_island(cr)
        else:
            key = self._bg_key()
            if key != self._bg_key_cached:
                sx, sy = cr.get_target().get_device_scale()
                surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(self.win_w * sx), int(self.win_h * sy))
                surf.set_device_scale(sx, sy)
                self._paint_island(cairo.Context(surf))
                self._bg_surf, self._bg_key_cached = surf, key
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_surface(self._bg_surf, 0, 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
        x, y, w, h, r = self.geo
        bw = self.cfg["border_width"]
        rounded_rect(cr, x + bw, y + bw, w - 2 * bw, h - 2 * bw, r)   # clip children to the shape
        cr.clip()
        return False

    def _paint_island(self, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        x, y, w, h, r = self.geo
        bw = self.cfg["border_width"]
        a = self.alpha
        bg = rgb(PAL["bg"])
        rounded_rect(cr, x + bw / 2, y + bw / 2, w - bw, h - bw, r)
        if PAL["glass"]:
            cr.save()
            cr.clip()
            if self._backdrop:                                      # blurred copy of what is behind
                small, ox, oy, bw_, bh_ = self._backdrop
                cr.translate(ox, oy)
                cr.scale(bw_ / small.get_width(), bh_ / small.get_height())
                cr.set_source_surface(small, 0, 0)
                pat = cr.get_source()
                pat.set_filter(cairo.FILTER_BILINEAR)
                pat.set_extend(cairo.EXTEND_PAD)
                cr.paint_with_alpha(a)
                cr.identity_matrix()
            ga = PAL["glass_alpha"]
            ga += (0.97 - ga) * 0.55 * clamp01(self.ex.v)             # denser when the notepad is open: readable
            cr.set_source_rgba(*bg, ga * a)                          # frosted tint
            cr.paint()
            sheen = cairo.LinearGradient(0, y, 0, y + h)             # soft light from above
            top_a = 0.16 if PAL["dark"] else 0.55
            sheen.add_color_stop_rgba(0, 1, 1, 1, top_a * a)
            sheen.add_color_stop_rgba(0.45, 1, 1, 1, 0.03 * a)
            sheen.add_color_stop_rgba(1, 1, 1, 1, 0)
            cr.set_source(sheen)
            cr.paint()
            cr.restore()
            rounded_rect(cr, x + bw + 0.5, y + bw + 0.5, w - 2 * bw - 1, h - 2 * bw - 1, max(0, r - bw))
            cr.set_source_rgba(1, 1, 1, (0.10 if PAL["dark"] else 0.45) * a)   # glass edge highlight
            cr.set_line_width(1)
            cr.stroke()
        else:
            cr.set_source_rgba(*bg, a)
            cr.fill()
        if bw > 0:
            rounded_rect(cr, x + bw / 2, y + bw / 2, w - bw, h - bw, r)
            cr.set_source_rgba(*rgb(PAL["border"]), a)               # the red outline
            cr.set_line_width(bw)
            cr.stroke()
    def _apply(self):
        """Island rect + content fades from the two tweens (called every frame).

        Appear: a small pill blooms from the centre of the top slot (iPhone style), springing a
        little past full size. Expand: the pill grows downward into the notepad."""
        ex, ap = self.ex.v, self.ap.v
        exc = clamp01(ex)
        seed_w, seed_h = self.ch * 1.15, self.ch * 0.6
        wc = max(seed_w * 0.7, seed_w + (self.cw - seed_w) * ap)
        hc = max(seed_h * 0.7, seed_h + (self.ch - seed_h) * ap)
        w = min(wc + (self.ew - wc) * ex, self.ew * 1.1)
        h = min(hc + (self.eh - hc) * ex, self.eh * 1.08)
        y = self.top + (self.ch - hc) / 2 * (1 - exc)            # centred in the slot, then anchored
        r = min(h / 2, w / 2, hc / 2 + (EXP_RADIUS - hc / 2) * exc)
        self.alpha = clamp01(ap * 4)
        self.geo = ((self.win_w - w) / 2, y, w, h, r)
        self.exp_box.set_opacity(clamp01((ex - 0.5) / 0.4) * self.alpha)
        self.cmp_box.set_opacity(clamp01((ap - 0.35) / 0.4) * (1 - clamp01(ex / 0.35)))
        self.fixed.move(self.cmp_box, (self.win_w - self.cw) // 2, int(self.top))
        self.fixed.move(self.exp_box, (self.win_w - self.ew) // 2, int(self.top))
        self._set_input_shape()
        self.queue_draw()

    def _set_input_shape(self):
        gw = self.get_window()
        if not gw:
            return
        x, y, w, h, _ = self.geo
        y0 = max(0, int(y))
        h2 = max(0, int(y + h) - y0)
        region = cairo.Region(cairo.RectangleInt(int(x), y0, int(w), h2)) if h2 else cairo.Region()
        gw.input_shape_combine_region(region, 0, 0)   # clicks outside the island pass through

    def _kick(self):
        if not self._anim_id:
            self._anim_id = GLib.timeout_add(16, self._anim_tick)

    def _anim_tick(self):
        now = time.monotonic()
        a, b = self.ex.step(now), self.ap.step(now)
        self._apply()
        if a or b:
            return True
        self._anim_id = 0
        return False

    def _monitor(self):
        disp = Gdk.Display.get_default()
        mon = None
        if self.cfg["monitor"] == "pointer":
            _s, px, py = disp.get_default_seat().get_pointer().get_position()
            mon = disp.get_monitor_at_point(px, py)
        return mon or disp.get_primary_monitor() or disp.get_monitor(0)

    def _place(self):
        g = self._monitor().get_geometry()
        x, y = g.x + (g.width - self.win_w) // 2, g.y
        log.info("show pill at %d,%d on %dx%d monitor (display backend: %s)", x, y, g.width,
                 g.height, type(Gdk.Display.get_default()).__name__)
        self._win_pos = (x, y)
        self.move(x, y)                                   # window hugs the top edge of the screen

    def _capture_backdrop(self):
        """Best effort frosted-glass blur: snapshot the screen behind the (still hidden) window and
        blur it. Only works where apps may read the screen (X11); otherwise the glass is simply
        translucent. A black snapshot (compositor owns the screen) is ignored."""
        self._backdrop = None
        if not (self.cfg["glass"] and self.cfg["glass_blur"]):
            return
        try:
            if "X11" not in type(Gdk.Display.get_default()).__name__:
                return
            root = Gdk.get_default_root_window()
            x, y = self._win_pos
            x0, y0 = max(0, x), max(0, y)
            w, h = min(self.win_w, root.get_width() - x0), min(self.win_h, root.get_height() - y0)
            if w < 20 or h < 20:
                return
            pb = Gdk.pixbuf_get_from_window(root, x0, y0, w, h)
            if pb is None:
                return
            px = pb.get_pixels()
            if max(px[::max(1, len(px) // 3000)]) < 12:      # black: nothing useful to blur
                return
            src = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
            small = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, w // 10), max(1, h // 10))
            c = cairo.Context(small)
            c.scale(small.get_width() / w, small.get_height() / h)
            c.set_source_surface(src, 0, 0)
            c.get_source().set_filter(cairo.FILTER_BEST)
            c.paint()
            self._backdrop = (small, x0 - x, y0 - y, w, h)
        except Exception as e:  # noqa: BLE001 - cosmetic only, never break showing the pill
            log.debug("no backdrop blur: %s", e)


    # -------------------------------------------------------- state machine
    def show_island(self):
        if self.state != "hidden":
            if not self._really_visible():
                self._resurface()                     # the window manager hid us (Win+D, minimise ...)
            elif self.cfg["focus_on_show"]:
                self.present()
            return
        self.state, self._was_active = "compact", False
        self._bump()
        self.ex.v = self.ap.v = 0.0
        self.ex.a = self.ap.a = None
        self._page = "notes"
        self.stack.set_visible_child_name("notes")
        self.exp_box.set_sensitive(False)
        self.cmp_box.set_sensitive(True)
        focus = self.cfg["focus_on_show"]
        self.set_accept_focus(focus)
        self.set_focus_on_map(focus)
        self._place()
        self._capture_backdrop()
        self._apply()
        self.deiconify()                              # never re-map as "minimised" (stale GDK flag)
        self.show_all()
        self.exp_box.hide()
        self.undo_btn.hide()
        self.sw.refresh()
        self.refresh_tasks()
        self._sync_ui()
        if focus:
            self.present()
            self.set_focus(None)
            GLib.timeout_add(500, self._focus_check)
        GLib.timeout_add(900, self._visible_check)
        self._start_timers()
        self.ap.go(1.0, self._dur(0.6), ease_appear)
        self._kick()

    def _visible_check(self):
        """Safety net: we asked to show the pill but the WM keeps it hidden -> bring it back."""
        if self.state != "hidden" and not self._really_visible():
            self._resurface()
        return False

    def _focus_check(self):
        if self.state == "compact" and not self.is_active():
            log.warning("the pill did not get keyboard focus (focus-stealing prevention?): Space cannot "
                        "reach it. Clicking the pill opens the notepad instead.")
        return False

    def expand(self):
        if self.state != "compact":
            return
        self.state = "expanded"
        self._bump()
        self.set_accept_focus(True)
        self.refresh_tasks(scroll_end=True)
        self._sync_ui()
        self.exp_box.show_all()
        self.undo_btn.set_visible(self._undo is not None)
        self.exp_box.set_sensitive(True)
        self.cmp_box.set_sensitive(False)
        self._update_compact_mode()
        self.present()
        self.entry.grab_focus()
        self.ex.go(1.0, self._dur(0.55), ease_expand)
        self._kick()

    def collapse(self):
        if self.state != "expanded":
            return
        self.state = "compact"
        self._bump()
        self.exp_box.set_sensitive(False)
        self.cmp_box.set_sensitive(True)
        self.set_focus(None)
        self._update_compact_mode()

        def done():
            if self.state == "compact":
                self.exp_box.hide()
                self._page = "notes"
                self.stack.set_visible_child_name("notes")
        self.ex.go(0.0, self._dur(0.36), ease_out_cubic, done)
        self._kick()

    def hide_island(self):
        """Always converges to hidden, from any state, however often it is called."""
        if self.state == "hidden":
            self._ensure_hidden()
            return
        self.state = "hidden"
        self.exp_box.set_sensitive(False)
        self._update_compact_mode()
        dur = self._dur(0.3)
        self.ex.go(0.0, self._dur(0.25), ease_out_cubic)
        self.ap.go(0.0, dur, ease_in_cubic, self._ensure_hidden)     # shrinks back into the top slot
        self._kick()
        GLib.timeout_add(int(dur * 1000) + 400, self._watchdog)   # belt and braces

    def _ensure_hidden(self):
        if self.state == "hidden" and self.get_visible():
            self.hide()
            self.deiconify()                          # an unmapped window forgets "minimised"
        return False

    # -- the window manager can hide us behind our back (Win+D "show desktop", minimise)
    def _really_visible(self):
        """True only if the pill is actually on screen."""
        gw = self.get_window()
        if gw is None or not self.get_visible():
            return False
        st = gw.get_state()
        return gw.is_viewable() and not (st & (Gdk.WindowState.ICONIFIED | Gdk.WindowState.WITHDRAWN))

    def _finish_animations(self):
        for tw in (self.ex, self.ap):
            if tw.a:
                tw.v, tw.a = tw.a[1], None
        self._apply()

    def _resurface(self):
        """We believe the pill is open but the WM hid it: bring it back instead of hiding it."""
        log.info("the pill was hidden by the window manager - bringing it back")
        self._bump()
        self.deiconify()
        self._finish_animations()
        self.present()
        GLib.timeout_add(300, self._resurface_check)

    def _resurface_check(self):
        if self.state != "hidden" and not self._really_visible():
            log.info("still not visible - re-mapping the window")
            self.hide()
            self.deiconify()
            self.show_all()
            if self.state == "compact":
                self.exp_box.hide()
            self.undo_btn.set_visible(self._undo is not None and self.state == "expanded")
            self._update_compact_mode()
            self._apply()
            self.present()
        return False

    def _watchdog(self):
        if self.state == "hidden" and not self.ap.a and not self.ex.a:
            self._ensure_hidden()
        return False

    def toggle_island(self):
        """Deterministic: visible -> hide, hidden -> show. Repeats from a held key are ignored."""
        now = time.monotonic()
        if now - self._last_toggle < 0.35:
            return
        self._last_toggle = now
        if self.state == "hidden":
            self.show_island()
        elif not self._really_visible():
            self._resurface()                         # first press brings it back after Win+D
        else:
            self.hide_island()

    def focus_island(self):
        if self.state == "hidden":
            self.show_island()
        elif not self._really_visible():
            self._resurface()
            return
        self.present()

    # -------------------------------------------------------- settings page (inside the pill)
    def show_settings_page(self):
        if self.state == "hidden":
            self.show_island()
        if self.state == "compact":
            self.expand()
        if not self._panel:
            self._panel = SettingsPanel(self, self.show_notes_page)
            self.stack.add_named(self._panel, "settings")
        else:
            self._panel.rebuild()
        self._panel.show_all()
        self._page = "settings"
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_visible_child_name("settings")
        self.set_focus(None)
        self._bump()

    def show_notes_page(self):
        back = Gtk.StackTransitionType.SLIDE_RIGHT if self._page == "detail" else Gtk.StackTransitionType.CROSSFADE
        self.stack.set_transition_type(back)
        self._page = "notes"
        self.stack.set_visible_child_name("notes")
        self.entry.grab_focus()
        self._bump()

    # -------------------------------------------------------- task detail page (inside the pill)
    def _on_row_activated(self, _box, row):
        tid = row.get_name()
        if tid in self._tasks_by_id:
            self.show_task_detail(tid)

    def show_task_detail(self, tid):
        """Slide in a page with the complete text of one task."""
        task = self._tasks_by_id.get(tid)
        if task is None or self.state != "expanded":
            return
        if self._detail is None:
            self._detail = TaskDetail(self, self.show_notes_page)
            self.stack.add_named(self._detail, "detail")
        self._detail_id = tid
        self._detail.update(task, self.sw.running and self.sw.task_id == tid)
        self._detail.show_all()
        self._page = "detail"
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT)
        self.stack.set_visible_child_name("detail")
        self.set_focus(None)
        self._bump()

    def _refresh_detail(self):
        """Keep the open detail page in step with the note (timer, done, edits, deletion)."""
        if self._page != "detail" or self._detail is None:
            return
        task = self._tasks_by_id.get(self._detail_id)
        if task is None:
            self.show_notes_page()                    # the task is gone (deleted / reworded elsewhere)
        else:
            self._detail.update(task, self.sw.running and self.sw.task_id == task.id)

    def _toggle_settings(self):
        if self._page == "settings":
            self.show_notes_page()
        else:
            self.show_settings_page()

    open_settings = show_settings_page

    # -------------------------------------------------------- auto-hide
    def _bump(self, *_):
        self._last_input = time.monotonic()

    def _set_hover(self, inside):
        self._hover = inside
        self._bump()

    def _start_timers(self):
        if not self._tick_id:
            self._tick_id = GLib.timeout_add(1000, self._tick)
        if not self._ah_id and self.cfg["auto_hide_seconds"] > 0:
            self._ah_id = GLib.timeout_add(500, self._autohide_check)

    def _autohide_check(self):
        secs = self.cfg["auto_hide_seconds"]
        if self.state == "hidden" or secs <= 0:
            self._ah_id = 0                          # nothing to watch: stop waking up
            return False
        if self.in_subpage or (self.sw.running and not self.cfg["auto_hide_when_running"]):
            return True
        typing = self.state == "expanded" and self.entry.get_text().strip() != ""
        if self._hover or typing:                    # never hide under the cursor or mid-sentence
            self._bump()
            return True
        if time.monotonic() - self._last_input >= secs:
            log.debug("auto-hide after %ss idle", secs)
            self.hide_island()
        return True

    # -------------------------------------------------------- events
    def _on_key(self, _w, ev):
        self._bump()
        key = Gdk.keyval_name(ev.keyval)
        if ev.state & Gdk.ModifierType.CONTROL_MASK and key in ("comma", "s", "S"):
            if self.state == "expanded":
                self._toggle_settings()
            elif self.state == "compact":
                self.show_settings_page()
            return True
        if self.state == "compact":
            if self._game_wanted() and key in ("Up", "w", "W"):
                self.game.jump_input()
                return True
            if key == "space":
                self.expand()
                return True
            if key in ("Return", "KP_Enter"):
                self._toggle()
                return True
            if key == "Escape":
                self.hide_island()
                return True
        elif self.state == "expanded" and key == "Escape":
            if self._page in ("settings", "detail"):
                self.show_notes_page()
            else:
                self.collapse()
            return True
        return False

    def _on_pill_click(self, _w, ev):
        self._bump()
        if self.state == "compact" and self._game_wanted():          # the game is on screen
            if ev.button == 1:
                self.game.jump_input()                              # click = jump
            elif ev.button == 3:
                self.expand()                                       # right-click = notepad
            elif ev.button == 2:
                self._toggle()                                      # middle-click = start/pause
            return True
        if self.state == "compact" and ev.button == 1:
            # With keyboard focus the click starts/pauses the timer. If the pill has no focus (the
            # window manager refused it, or focus_on_show is off) Space cannot work, so a click
            # opens the notepad instead: it can always be reached.
            if self.cfg["focus_on_show"] and self.is_active():
                self._toggle()
            else:
                self.expand()
        return True

    def _on_active(self, *_):
        if self.is_active():
            self._was_active = True
        elif self._was_active and self.state == "expanded" and self.cfg["collapse_on_blur"]:
            GLib.timeout_add(200, self._blur_check)

    def _blur_check(self):
        if self.state == "expanded" and not self.is_active() and not self.in_subpage:
            self.collapse()
        return False

    # -------------------------------------------------------- actions
    def _safe(self, fn, *args):
        """Run a vault operation; show a readable message instead of crashing."""
        try:
            return fn(*args)
        except VaultError as e:
            log.error("vault: %s", e)
            self._toast(str(e).upper(), error=True)
        except Exception:
            log.exception("unexpected error in %s", getattr(fn, "__name__", fn))
            self._toast("UNEXPECTED ERROR - SEE LOG", error=True)
        return None

    def _toast(self, text, error=False, undo=False, secs=6):
        if self._toast_id:
            GLib.source_remove(self._toast_id)
            self._toast_id = 0
        ctx = self.status_lbl.get_style_context()
        (ctx.add_class if error else ctx.remove_class)("err")
        self.status_lbl.set_text(text)
        self.status_lbl.set_tooltip_text(text or None)           # full text if it had to be shortened
        self.undo_btn.set_visible(undo)
        self._toast_on = bool(text)
        self._sync_head()
        if text:
            self._toast_id = GLib.timeout_add_seconds(secs, self._clear_toast)

    def _clear_toast(self):
        self._toast_id = 0
        self.status_lbl.set_text("")
        self.status_lbl.set_tooltip_text(None)
        self.undo_btn.hide()
        self._undo = None
        self._toast_on = False
        self._sync_head()
        return False

    def _sync_head(self):
        """Left header label; shrinks to just the dot while a message needs the room."""
        run, acc = self.sw.running, PAL["accent"]
        dot = f'<span foreground="{acc}">●</span>' if run else "○"
        word = "" if self._toast_on else ("TIMER · LIVE" if run else "TIMER")
        self.head_lbl.set_markup(f"{dot} {word}".rstrip())

    def _commit(self, out):
        tid, delta = out
        if tid and delta > 0:
            if self._safe(self.store.add_time, tid, delta) is None and self.state != "hidden":
                self._toast("TIME NOT SAVED: TASK CHANGED", error=True)
            self.refresh_tasks()

    def _toggle(self, *_):
        self.sw.refresh()
        if self.sw.running:
            self._commit(self.sw.pause())
        else:
            self.sw.start()
        self._sync_ui()

    def _reset(self, *_):
        self.sw.refresh()
        self._commit(self.sw.reset())
        self._sync_ui()

    def _start_task(self, tid):
        self.sw.refresh()
        if self.sw.task_id == tid and self.sw.running:
            self._commit(self.sw.pause())
        else:
            self._commit(self.sw.switch(tid))
        self.refresh_tasks()
        self._sync_ui()

    def _set_done(self, tid, done):
        self.sw.refresh()
        if done and self.sw.task_id == tid and self.sw.running:
            self._commit(self.sw.pause())
        self._safe(self.store.set_done, tid, done)
        self.refresh_tasks()
        self._sync_ui()

    def _delete(self, tid):
        removed = self._safe(self.store.delete_task, tid)
        if not removed:
            return
        self.sw.refresh()
        if self.sw.task_id == tid:
            self.sw.detach()               # drop the session together with the task
        self._undo = removed
        self.refresh_tasks()
        self._sync_ui()
        self._toast("DELETED", undo=True)

    def _undo_delete(self, *_):
        if self._undo:
            self._safe(self.store.restore, *self._undo)
            self._undo = None
            self._toast("")
            self.refresh_tasks()

    def _add(self, entry):
        text = entry.get_text().strip()
        task = text and self._safe(self.store.add_task, text)
        if task:
            entry.set_text("")
            self.refresh_tasks(scroll_end=True, highlight=task.id)   # jump to it and flash it
            self._toast("ADDED", secs=2)
        entry.grab_focus()

    def _on_vault_changed(self, *_):
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._debounce = GLib.timeout_add(300, self._debounced_refresh)

    def _debounced_refresh(self):
        self._debounce = 0
        if self.state != "hidden":
            self.refresh_tasks()
        return False

    # -------------------------------------------------------- view
    def _scroll_to(self, value):
        """value=None -> bottom. Layout is asynchronous, so apply it a few times."""
        def go():
            adj = self.scroller.get_vadjustment()
            bottom = max(0.0, adj.get_upper() - adj.get_page_size())
            adj.set_value(bottom if value is None else min(value, bottom))
            return False
        GLib.idle_add(go)
        GLib.timeout_add(80, go)
        GLib.timeout_add(250, go)

    def refresh_tasks(self, scroll_end=False, highlight=None):
        tasks = self._safe(self.store.list_tasks)
        if tasks is None:
            return
        self.store.migrate_timer(self.sw)                          # old ^t- id -> new id
        self._tasks_by_id = {t.id: t for t in tasks}
        keep = self.scroller.get_vadjustment().get_value()
        if highlight:                                   # survives the refresh our own write triggers
            self._hl_task, self._hl_until = highlight, time.monotonic() + 1.8
        highlight = self._hl_task if time.monotonic() < self._hl_until else None
        key = (tuple((t.id, t.text, t.done, t.seconds) for t in tasks), self.sw.task_id, self.sw.running, highlight)
        if key == self._render_key:                                  # nothing changed (e.g. the echo of our
            if scroll_end:                                           # own write): don't rebuild the rows
                self._scroll_to(None)
            return
        self._render_key = key
        for row in self.list.get_children():
            self.list.remove(row)
        self._hl_row = None
        if len(tasks) > MAX_ROWS:                                   # keep the widget light on huge notes
            older = Gtk.ListBoxRow()
            older.set_activatable(False)
            older.set_can_focus(False)
            lbl = Gtk.Label(label=f"… {len(tasks) - MAX_ROWS} older tasks are in your note", xalign=0)
            lbl.get_style_context().add_class("time")
            older.add(lbl)
            self.list.add(older)
            tasks = tasks[-MAX_ROWS:]
        for t in tasks:
            active = t.id == self.sw.task_id
            row = Gtk.ListBoxRow()
            row.set_can_focus(False)
            row.set_name(t.id)
            if t.id == highlight:
                row.get_style_context().add_class("newrow")
                self._hl_row = row
            box = Gtk.Box(spacing=2)
            mark = "●" if t.done else ("◉" if active else "○")
            chk = self._flat(mark, lambda _b, tid=t.id, d=t.done: self._set_done(tid, not d), "big")
            if active and not t.done:
                chk.get_style_context().add_class("dot-on")
            lbl = Gtk.Label(xalign=0, ellipsize=3)
            esc = GLib.markup_escape_text(t.text)
            lbl.set_markup(f"<s>{esc}</s>" if t.done else esc)
            lbl.set_tooltip_text(t.text)
            ctx = lbl.get_style_context()
            ctx.add_class("task")
            if active:
                ctx.add_class("active")
            tm = Gtk.Label(label=fmt_hms(t.seconds)[:-3] if t.seconds else "")
            tm.get_style_context().add_class("time")
            timing = self.sw.running and active                      # this task is being timed right now
            play = self._flat("❚❚" if timing else "▶", lambda _b, tid=t.id: self._start_task(tid), "big")
            if timing:
                play.get_style_context().add_class("dot-on")
            play.set_tooltip_text("Pause the timer" if timing else "Start the timer on this task")
            dele = self._flat("×", lambda _b, tid=t.id: self._delete(tid), "big", "del")
            dele.set_tooltip_text("Delete task")
            box.pack_start(chk, False, False, 0)
            box.pack_start(lbl, True, True, 0)
            box.pack_end(dele, False, False, 0)
            box.pack_end(play, False, False, 0)
            box.pack_end(tm, False, False, 2)
            row.add(box)
            self.list.add(row)
        self.list.show_all()
        self._scroll_to(None if scroll_end else keep)
        self._refresh_detail()
        if self._hl_row is not None:
            GLib.timeout_add(max(100, int((self._hl_until - time.monotonic()) * 1000)),
                             self._clear_highlight, self._hl_row)

    def _clear_highlight(self, row):
        row.get_style_context().remove_class("newrow")
        return False

    def _sync_ui(self):
        run, acc = self.sw.running, PAL["accent"]
        ctx = self.go.get_style_context()
        self.go.set_label("PAUSE" if run else "START")
        (ctx.remove_class if run else ctx.add_class)("go")
        self._sync_head()
        self.cmp_dot.set_markup(f'<span foreground="{acc if run else PAL["muted"]}" size="large">●</span>')
        self._update_compact_mode()
        self._paint_time()

    def _game_wanted(self):
        """The idle game replaces the digits while the stopwatch is not running."""
        return self.cfg["mario_game"] and not self.sw.running

    def _update_compact_mode(self):
        want = self._game_wanted()
        self.cmp_stack.set_visible_child_name("game" if want else "time")
        if want and self.state == "compact":
            self.game.start()
        else:
            self.game.stop()
        self.cmp_box.set_tooltip_text(
            f"Click / Up: jump   Space: notepad   Enter: start timer   Best: {self.game.world.best}" if want
            else "Space: notepad   Enter: start/pause   Esc: hide")


    def _paint_time(self):
        if self.state != "hidden":
            el, run = self.sw.elapsed, self.sw.running
            self.cmp_time.update(el, run)
            self.display.update(el, run)

    def _tick(self):
        """Once per second boundary while visible; not at all while hidden."""
        self._tick_id = 0
        if self.state == "hidden":
            return False
        if self.sw.reload_if_changed():              # e.g. the MCP server changed the timer
            self._sync_ui()
            self.refresh_tasks()
        self._paint_time()
        ms = 1000 if not self.sw.running else int((1 - self.sw.elapsed % 1) * 1000) + 20
        self._tick_id = GLib.timeout_add(max(60, ms), self._tick)
        return False


# ------------------------------------------------------------------ application
COMMANDS = ("toggle", "show", "hide", "expand", "collapse", "focus", "settings", "start", "quit")


class App(Gtk.Application):
    """Single instance. Every command is also a GAction on D-Bus, so shortcuts can
    call it in ~10 ms without starting Python (see nothing-tasks-ctl)."""

    def __init__(self):
        super().__init__(application_id="dev.nothing.tasks",
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.hold()                       # stay alive while the pill is hidden
        self.win = Island()
        for name in COMMANDS:
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", lambda _a, _p, n=name: self.run_cmd(n))
            self.add_action(act)
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, self._on_signal)
        log.info("nothing-tasks %s started (session=%s)", __version__,
                 GLib.getenv("XDG_SESSION_TYPE"))

    def _on_signal(self):
        log.info("signal received, quitting")
        self.quit()
        return GLib.SOURCE_REMOVE

    def run_cmd(self, cmd):
        w = self.win
        if cmd == "toggle":
            w.toggle_island()
        elif cmd == "show":
            w.show_island()
        elif cmd == "hide":
            w.hide_island()
        elif cmd == "expand":
            w.show_island()
            w.expand()
        elif cmd == "collapse":
            w.collapse()
        elif cmd == "focus":
            w.focus_island()
        elif cmd == "settings":
            w.show_settings_page()
        elif cmd == "quit":
            self.quit()
        # "start": run in the background, show nothing

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        cmd = args[0] if args else "toggle"
        if cmd not in COMMANDS:
            cl.printerr_literal(f"nothing-tasks: unknown command '{cmd}'\n")
            return 2
        self.run_cmd(cmd)
        return 0


def main(argv=None):
    GLib.set_prgname("nothing-tasks")
    GLib.set_application_name(APP_NAME)
    sys.excepthook = lambda *a: log.critical("uncaught", exc_info=a)
    rc = App().run(["nothing-tasks"] + list(argv or []))
    Gdk.notify_startup_complete()         # never leave a "launching..." item in the dock
    return rc
