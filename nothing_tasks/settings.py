"""Settings page that lives inside the expanded pill (no separate window).
Every feature of the pill/notepad is configurable here; changes apply live and are saved."""
from __future__ import annotations

import logging
import os
import subprocess
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from . import APP_NAME, __version__, system
from .core import DEFAULT_CONFIG, STATE_DIR, normalize_binding

log = logging.getLogger("nothing_tasks")


class IconArea(Gtk.DrawingArea):
    """Small line icons drawn with cairo, so they never depend on font glyphs."""

    def __init__(self, kind: str, size: int = 22):
        super().__init__()
        self.kind = kind
        self.set_size_request(size, size)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self._draw)

    def _draw(self, _w, cr):
        from .ui import PAL, rgb  # imported late: ui imports this module
        k = self.get_allocated_width() / 22.0
        cr.scale(k, k)
        cr.set_source_rgb(*rgb(PAL["accent"]))
        cr.set_line_width(1.7)
        cr.set_line_cap(1)                            # round
        cr.set_line_join(1)
        if self.kind == "mail":                        # envelope
            cr.rectangle(2.5, 5, 17, 12)
            cr.stroke()
            cr.move_to(3, 6)
            cr.line_to(11, 12.2)
            cr.line_to(19, 6)
            cr.stroke()
        else:                                          # git branch: two nodes on a line + one branched off
            for cx, cy in ((6.5, 4.8), (6.5, 17.2), (16, 8.5)):
                cr.new_sub_path()
                cr.arc(cx, cy, 2.1, 0, 6.2832)
            cr.stroke()
            cr.move_to(6.5, 6.9)
            cr.line_to(6.5, 15.1)
            cr.stroke()
            cr.move_to(16, 10.6)
            cr.curve_to(16, 14.2, 6.5, 12.2, 6.5, 15.1)
            cr.stroke()
        return False


class SettingsPanel(Gtk.Box):
    def __init__(self, island, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.island = island
        self._pending: dict = {}
        self._flush_id = 0
        self.get_style_context().add_class("spanel")
        self.set_margin_start(12)
        self.set_margin_end(12)

        head = Gtk.Box(spacing=8)
        back = island._flat("‹  BACK", lambda *_: on_back(), "backbtn")
        title = Gtk.Label(label="SETTINGS", xalign=1)
        title.get_style_context().add_class("tiny")
        head.pack_start(back, False, False, 0)
        head.pack_end(title, True, True, 6)
        self.pack_start(head, False, False, 0)

        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)   # wheel scrolls, no reserved bar
        self.scroll.set_overlay_scrolling(True)
        self.pack_start(self.scroll, True, True, 0)
        self.rebuild()

    # -------------------------------------------------------- helpers
    @property
    def cfg(self):
        return self.island.cfg

    def _heading(self, text):
        lbl = Gtk.Label(label=text.upper(), xalign=0)
        lbl.get_style_context().add_class("heading")
        self.grid.attach(lbl, 0, self.row, 2, 1)
        self.row += 1

    def _note(self, text, cls="hint"):
        h = Gtk.Label(label=text, xalign=0, wrap=True, max_width_chars=44, width_chars=1,
                      wrap_mode=Pango.WrapMode.WORD_CHAR)
        h.get_style_context().add_class(cls)
        self.grid.attach(h, 0, self.row, 2, 1)
        self.row += 1
        return h

    def _add(self, label, widget, hint=None):
        lbl = Gtk.Label(label=label, xalign=0, hexpand=True, wrap=True, max_width_chars=26, width_chars=1,
                        wrap_mode=Pango.WrapMode.WORD_CHAR)
        widget.set_valign(Gtk.Align.CENTER)
        widget.set_halign(Gtk.Align.END)
        self.grid.attach(lbl, 0, self.row, 1, 1)
        self.grid.attach(widget, 1, self.row, 1, 1)
        self.row += 1
        if hint:
            self._note(hint)

    def _set(self, key, value, delay=0):
        """Queue a config change; sliders are debounced so dragging stays smooth."""
        self._pending[key] = value
        if self._flush_id:
            GLib.source_remove(self._flush_id)
        self._flush_id = GLib.timeout_add(delay or 1, self._flush)

    def _flush(self):
        self._flush_id = 0
        changes, self._pending = self._pending, {}
        self.island.update_config(changes)
        return False

    def _switch(self, key):
        sw = Gtk.Switch(active=bool(self.cfg[key]))
        sw.connect("notify::active", lambda w, _p: self._set(key, w.get_active()))
        return sw

    def _number(self, key, lo, hi, integer=False, width=6):
        """Typed number field. Deliberately NOT a slider or +/- spinner: sizes are never changed by
        dragging or by the mouse wheel. Type a value and press Enter (or click away) to apply."""
        fmt = (lambda v: str(int(v))) if integer else (lambda v: f"{v:g}")
        e = Gtk.Entry(text=fmt(self.cfg[key]), width_chars=width, xalign=1.0)
        e.set_input_purpose(Gtk.InputPurpose.NUMBER)
        e.set_tooltip_text(f"{fmt(lo)} to {fmt(hi)} - type a number, then press Enter")

        def commit(*_):
            self._apply_number(key, e, lo, hi, integer, fmt)
            return False
        e.connect("activate", commit)
        e.connect("focus-out-event", commit)
        return e

    def _apply_number(self, key, entry, lo, hi, integer, fmt=None):
        fmt = fmt or ((lambda v: str(int(v))) if integer else (lambda v: f"{v:g}"))
        try:
            v = float(entry.get_text().strip().replace(",", "."))
            v = min(hi, max(lo, round(v) if integer else v))
        except ValueError:
            v = self.cfg[key]                                  # not a number: keep the old value
        entry.set_text(fmt(v))
        if v != self.cfg[key]:
            self._set(key, v)

    def _no_wheel(self, widget):
        """The mouse wheel scrolls the page; it must never change a value under the pointer."""
        def forward(_w, ev):
            adj = self.scroll.get_vadjustment()
            step = max(adj.get_step_increment(), 30.0)
            if ev.direction == Gdk.ScrollDirection.UP:
                adj.set_value(adj.get_value() - step)
            elif ev.direction == Gdk.ScrollDirection.DOWN:
                adj.set_value(adj.get_value() + step)
            elif ev.direction == Gdk.ScrollDirection.SMOOTH:
                adj.set_value(adj.get_value() + ev.delta_y * step)
            return True
        widget.connect("scroll-event", forward)
        return widget

    def _color(self, key):
        rgba = Gdk.RGBA()
        rgba.parse(self.cfg[key])
        btn = Gtk.ColorButton.new_with_rgba(rgba)
        btn.set_size_request(110, -1)

        def picked(w):
            c = w.get_rgba()
            r, g, b = (round(v * 255) for v in (c.red, c.green, c.blue))
            self._set(key, f"#{r:02X}{g:02X}{b:02X}", 120)
        btn.connect("color-set", picked)
        return btn

    def _entry(self, key, width=12):
        e = Gtk.Entry(text=str(self.cfg[key]), width_chars=width)
        e.connect("activate", lambda w: self._set(key, w.get_text()))
        e.connect("focus-out-event", lambda w, _e: self._set(key, w.get_text()) or False)
        return e

    def _combo(self, key, options):
        cb = Gtk.ComboBoxText()
        for o in options:
            cb.append_text(o)
        cb.set_active(options.index(self.cfg[key]))
        cb.connect("changed", lambda w: self._set(key, w.get_active_text()))
        return self._no_wheel(cb)

    # -------------------------------------------------------- content
    def rebuild(self):
        old = self.scroll.get_child()
        if old:
            self.scroll.remove(old)
            old.destroy()
        self.grid = Gtk.Grid(column_spacing=12, row_spacing=12, margin_right=8, margin_bottom=8)
        self.row = 0
        self._build()
        self.scroll.add(self.grid)
        self.grid.show_all()

    def _build(self):
        c = self.cfg
        self._heading("Obsidian")
        chooser = Gtk.FileChooserButton(title="Choose your vault folder",
                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        chooser.set_size_request(140, -1)
        chooser.set_width_chars(10)
        vault = os.path.expanduser(c["vault"])
        if os.path.isdir(vault):
            chooser.set_filename(vault)
        chooser.connect("file-set", lambda w: self._set("vault", w.get_filename()))
        self._no_wheel(chooser)
        self._add("Vault folder", chooser)
        self._add("Task note", self._entry("note"),
                  "Tasks are appended to this note inside the vault as  - [ ] text ⏱ 00:00:00")

        self._heading("Keyboard shortcut")
        box = Gtk.Box(spacing=8)
        self.sc_entry = Gtk.Entry(text=c["shortcut"], width_chars=8)
        self.sc_entry.connect("changed", self._on_sc_changed)
        apply_btn = Gtk.Button(label="Apply")
        apply_btn.connect("clicked", self._apply_shortcut)
        box.pack_start(self.sc_entry, True, True, 0)
        box.pack_start(apply_btn, False, False, 0)
        self._add("Open / close the pill", box)
        self.sc_msg = self._note("", "warn")
        self.sc_msg.set_no_show_all(True)                  # no empty gap when there is nothing to say
        self._on_sc_changed()
        self._check_gnome_shortcut()
        self._add("Register it automatically", self._switch("auto_shortcut"),
                  "Examples: <Alt>x   <Super>t   <Ctrl><Alt>n")

        self._heading("Appearance")
        self._add("Accent colour", self._color("accent"))
        self._add("Pill border colour", self._color("border_color"),
                  "The Add-a-task box border follows this colour.")
        self._add("Theme", self._combo("theme", ["auto", "dark", "light"]),
                  "auto follows the system light / dark setting.")
        self._add("Glass effect", self._switch("glass"),
                  "Frosted, see-through pill that blends with the system and your background.")
        self._add("Glass strength", self._number("glass_strength", 0, 100, True),
                  "0 to 100. 0 = solid, 100 = most see-through.")
        self._add("Blur what is behind", self._switch("glass_blur"),
                  "Best effort: only where the desktop lets apps read the screen (X11). Otherwise the "
                  "glass is simply translucent. For a real blur on GNOME, the 'Blur my Shell' "
                  "extension can blur the app 'nothing-tasks'.")
        self._add("Seconds strip", self._switch("show_seconds_strip"))
        self._add("Show on monitor", self._combo("monitor", ["pointer", "primary"]),
                  "pointer = the screen your mouse is on.")

        self._heading("Sizes")
        self._note("Type a number, then press Enter.")
        self._add("Task input border (px)", self._number("input_border_width", 0, 12, True),
                  "0 to 12. The red outline of the Add-a-task box. Default 1.")
        self._add("Pill border width (px)", self._number("border_width", 0, 4))
        self._add("Pill size", self._number("pill_scale", 0.7, 1.5), "1 = normal. 0.7 to 1.5.")
        self._add("Task input size", self._number("input_scale", 0.6, 1.4),
                  "0.6 to 1.4. Default 0.85. Size of the Add-a-task box.")
        self._add("Task input width (%)", self._number("input_width", 50, 100, True),
                  "100 = as wide as the task list (and its highlight). Lower = narrower, centred.")
        self._add("Notepad size", self._number("notepad_scale", 0.7, 1.2),
                  "0.7 to 1.2. Default 0.9. Applies immediately.")
        self._add("Top distance (px)", self._number("top_margin", 0, 80, True))

        self._heading("Mario game")
        self._add("Show the game in the pill", self._switch("mario_game"),
                  "Plays in the pill while the stopwatch is stopped; the stopwatch replaces it while it runs.")
        self._add("Game colours", self._combo("game_theme", ["mario", "pill"]),
                  "mario = the Mario palette, pill = the pill's own grey and red.")
        best = Gtk.Box(spacing=8)
        self.best_lbl = Gtk.Label(label=str(self.island.game.world.best))
        reset_best = Gtk.Button(label="Reset")
        reset_best.connect("clicked", self._reset_best)
        best.pack_start(self.best_lbl, False, False, 0)
        best.pack_start(reset_best, False, False, 0)
        self._add("Best score", best,
                  "Click or Up / W: jump.   Space or right-click: notepad.   Enter or middle-click: "
                  "start the timer. It plays itself until you jump in.")

        self._heading("Animation")
        self._add("Animations", self._switch("animations"))
        self._add("Animation speed", self._number("animation_speed", 0.5, 2.0), "1 = normal. 0.5 to 2.")

        self._heading("Behaviour")
        self._add("Auto-hide after (sec)", self._number("auto_hide_seconds", 0, 600, True),
                  "0 = never. It never hides while your mouse is over it or you are typing.")
        self._add("Auto-hide while timing", self._switch("auto_hide_when_running"))
        self._add("Fold when clicking away", self._switch("collapse_on_blur"))
        self._add("Keyboard focus on show", self._switch("focus_on_show"),
                  "ON (default): Space opens the notepad, Enter starts/pauses, Esc hides. Turn it OFF only "
                  "if your auto-hide dock pops up when the pill appears; then click the pill to open "
                  "the notepad.")

        self._heading("System")
        auto = Gtk.Switch(active=system.is_autostart())
        auto.connect("notify::active", lambda w, _p: system.set_autostart(w.get_active()))
        self._add("Start at login", auto)
        self._add("Log level", self._combo("log_level", ["DEBUG", "INFO", "WARNING", "ERROR"]))

        row = Gtk.FlowBox(margin_top=12, selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8,
                          max_children_per_line=2, min_children_per_line=1, homogeneous=False)
        reset = Gtk.Button(label="Reset appearance")
        reset.connect("clicked", self._reset)
        logs = Gtk.Button(label="Open log folder")
        logs.connect("clicked", lambda *_: subprocess.Popen(["xdg-open", str(STATE_DIR)]))
        row.add(reset)
        row.add(logs)
        self.grid.attach(row, 0, self.row, 2, 1)
        self.row += 1

        self._heading("About")
        self.grid.attach(self._about_card(), 0, self.row, 2, 1)
        self.row += 1

    def _about_card(self):
        """Minimal card: app name + version, the developer, then two aligned contact rows."""
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.get_style_context().add_class("devcard")

        top = Gtk.Box(spacing=10)
        mark = Gtk.Label(label="●")
        mark.get_style_context().add_class("appmark")
        name = Gtk.Label(label=APP_NAME, xalign=0, ellipsize=3, width_chars=6)
        name.get_style_context().add_class("appname")
        ver = Gtk.Label(label=f"v{__version__}", valign=Gtk.Align.CENTER)
        ver.get_style_context().add_class("verbadge")
        top.pack_start(mark, False, False, 0)
        top.pack_start(name, False, False, 0)
        top.pack_end(ver, False, False, 0)
        card.pack_start(top, False, False, 0)
        card.pack_start(Gtk.Separator(), False, False, 0)

        who = Gtk.Box(spacing=14)
        avatar = Gtk.Label(label="A")
        avatar.get_style_context().add_class("avatar")
        avatar.set_size_request(48, 48)
        avatar.set_valign(Gtk.Align.CENTER)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, valign=Gtk.Align.CENTER)
        dev = Gtk.Label(label="Ashish", xalign=0)
        dev.get_style_context().add_class("devname")
        role = Gtk.Label(label="Developer", xalign=0)
        role.get_style_context().add_class("hint")
        text.pack_start(dev, False, False, 0)
        text.pack_start(role, False, False, 0)
        who.pack_start(avatar, False, False, 0)
        who.pack_start(text, False, False, 0)
        card.pack_start(who, False, False, 0)

        links = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        links.pack_start(self._link_row("mail", "ashishaxm11@gmail.com", "mailto:ashishaxm11@gmail.com",
                                        "Copy", self._copy_email), False, False, 0)
        links.pack_start(self._link_row("code", "github.com/ashishnxt", "https://github.com/ashishnxt/",
                                        "Open", None), False, False, 0)
        card.pack_start(links, False, False, 0)
        return card

    def _link_row(self, icon, label, uri, action, on_action):
        """[icon]  text ...........  [Copy|Open]  - icon and text open the link; one fixed-width action."""
        row = Gtk.Box(spacing=8)
        main = Gtk.Button()
        main.get_style_context().add_class("flat")
        main.get_style_context().add_class("devrow")
        main.set_can_focus(False)
        main.set_name(f"devlink:{uri}")
        inner = Gtk.Box(spacing=12)
        inner.pack_start(IconArea(icon), False, False, 0)
        lbl = Gtk.Label(label=label, xalign=0, ellipsize=3, width_chars=8)   # may shorten, never widens the page
        lbl.set_tooltip_text(label)
        inner.pack_start(lbl, True, True, 0)
        main.add(inner)
        main.connect("clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(uri, None))
        btn = Gtk.Button(label=action)
        btn.get_style_context().add_class("pillbtn")
        btn.set_size_request(64, -1)
        btn.set_valign(Gtk.Align.CENTER)
        btn.set_can_focus(False)
        btn.connect("clicked", on_action or (lambda *_: Gio.AppInfo.launch_default_for_uri(uri, None)))
        row.pack_start(main, True, True, 0)
        row.pack_start(btn, False, False, 0)
        return row

    @staticmethod
    def _copy_email(btn):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text("ashishaxm11@gmail.com", -1)
        btn.set_label("Copied")
        GLib.timeout_add(1500, lambda: btn.set_label("Copy") or False)

    def _on_sc_changed(self, *_):
        try:
            warn = system.check_binding(self.sc_entry.get_text().strip())
            self._say(("⚠ " + warn) if warn else "")
        except ValueError as e:
            self._say(f"⚠ {e}")

    def _check_gnome_shortcut(self):
        """Say what GNOME has registered right now, if that is not what is configured. Read in a thread:
        gsettings is slow, and this must never delay opening the page."""
        want = normalize_binding(self.cfg["shortcut"])

        def work():
            try:
                cur = system._current()
            except (RuntimeError, ValueError, SyntaxError):
                return
            if cur is None:
                msg = "No shortcut is registered with GNOME yet. Press Apply to register it."
            elif system._norm(cur["binding"]) != system._norm(want):
                msg = f"GNOME currently has {cur['binding']} registered. Press Apply to switch it to {want}."
            else:
                return
            GLib.idle_add(self._say_gnome, msg)
        threading.Thread(target=work, daemon=True).start()

    def _say_gnome(self, msg):
        if self.sc_msg.get_parent() is not None and not self.sc_msg.get_text():
            self._say(msg)
        return False

    def _say(self, text):
        self.sc_msg.set_text(text)
        self.sc_msg.set_visible(bool(text))

    def _apply_shortcut(self, *_):
        binding = self.sc_entry.get_text().strip()
        try:
            if not Gtk.accelerator_parse(binding)[0]:
                raise ValueError("not a valid key combination")
            cmd = system.set_shortcut(binding)
            self._set("shortcut", binding)
            log.info("shortcut %s -> %s", binding, cmd)
            self._say(f"✓ {binding} now opens and closes the pill")
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as e:
            log.warning("shortcut failed: %s", e)
            self._say(f"⚠ Could not set shortcut: {e}")

    def _reset_best(self, *_):
        self.island.game.reset_best()
        self.best_lbl.set_text("0")

    def _reset(self, *_):
        keep = {k: self.cfg[k] for k in ("vault", "note", "shortcut")}
        self.island.update_config({**DEFAULT_CONFIG, **keep})
        self.rebuild()
