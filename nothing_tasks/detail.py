"""Full-text view of one task, shown inside the pill (slides in over the task list)."""
from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango

from .core import fmt_hms


class TaskDetail(Gtk.Box):
    """Shows the complete task text (the list only has room for one ellipsised line), its state and
    time, and the few things you do with a task. All widgets have a tiny minimum width, so this page
    can never widen the notepad."""

    def __init__(self, island, on_back):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.island = island
        self.task = None
        self.get_style_context().add_class("dpanel")
        self.set_margin_start(12)
        self.set_margin_end(12)

        head = Gtk.Box(spacing=8)
        back = island._flat("‹  BACK", lambda *_: on_back(), "backbtn")
        title = Gtk.Label(label="TASK", xalign=1)
        title.get_style_context().add_class("tiny")
        head.pack_start(back, False, False, 0)
        head.pack_end(title, True, True, 6)
        self.pack_start(head, False, False, 0)

        chips = Gtk.Box(spacing=8)
        self.status_chip, self.time_chip = Gtk.Label(), Gtk.Label()
        for c in (self.status_chip, self.time_chip):
            c.get_style_context().add_class("chip")
            chips.pack_start(c, False, False, 0)
        self.pack_start(chips, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)     # long text: the wheel scrolls
        scroll.set_overlay_scrolling(True)
        self.text = Gtk.Label(xalign=0, yalign=0, wrap=True, wrap_mode=Pango.WrapMode.WORD_CHAR,
                              width_chars=1, max_width_chars=60)
        self.text.get_style_context().add_class("detailtext")
        scroll.add(self.text)
        self.pack_start(scroll, True, True, 0)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8, column_homogeneous=True)
        self.btn_timer = self._button("START", self._on_timer)
        self.btn_done = self._button("DONE", self._on_done)
        self.btn_copy = self._button("COPY", self._on_copy)
        self.btn_del = self._button("DELETE", self._on_delete, "danger")
        grid.attach(self.btn_timer, 0, 0, 1, 1)
        grid.attach(self.btn_done, 1, 0, 1, 1)
        grid.attach(self.btn_copy, 0, 1, 1, 1)
        grid.attach(self.btn_del, 1, 1, 1, 1)
        self.pack_start(grid, False, False, 4)

    @staticmethod
    def _button(label, cb, *classes):
        b = Gtk.Button(label=label)
        b.set_can_focus(False)
        for c in ("pill", *classes):
            b.get_style_context().add_class(c)
        b.connect("clicked", cb)
        return b

    # -- content
    def update(self, task, timing: bool):
        self.task = task
        self.text.set_text(task.text)
        if self.text.get_parent() is not None:
            self.text.get_parent().get_vadjustment().set_value(0)         # long text: start at the top
        done_ctx = self.status_chip.get_style_context()
        self.status_chip.set_text("DONE" if task.done else "OPEN")
        (done_ctx.add_class if task.done else done_ctx.remove_class)("done")
        self.time_chip.set_text(f"TIME {fmt_hms(task.seconds)}" if task.seconds else "NO TIME YET")
        ctx = self.btn_timer.get_style_context()
        self.btn_timer.set_label("PAUSE" if timing else "START")
        (ctx.remove_class if timing else ctx.add_class)("go")           # START is the primary action
        self.btn_done.set_label("REOPEN" if task.done else "DONE")

    # -- actions (the island does the work, then refreshes this page)
    def _on_timer(self, *_):
        if self.task:
            self.island._start_task(self.task.id)

    def _on_done(self, *_):
        if self.task:
            self.island._set_done(self.task.id, not self.task.done)

    def _on_copy(self, btn):
        if self.task:
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(self.task.text, -1)
            btn.set_label("COPIED")
            GLib.timeout_add(1200, lambda: btn.set_label("COPY") or False)

    def _on_delete(self, *_):
        if self.task:
            self.island._delete(self.task.id)
            self.island.show_notes_page()
