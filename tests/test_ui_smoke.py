"""Boots the real widget under a virtual display: show -> expand -> settings -> hide."""
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
    from nothing_tasks import ui, APP_NAME, __version__
    from nothing_tasks.ui import Island
    w = Island()
    def pump(sec=0.3):
        end = time.time() + sec
        while time.time() < end:
            while Gtk.events_pending(): Gtk.main_iteration()
            time.sleep(0.01)

    # --- appear animation: blooms in place at top-middle (centre fixed), no slide
    w.ap.v = w.ex.v = 0.0; w._apply()
    x0, y0, w0, h0, _ = w.geo
    w.ap.v = 1.0; w._apply()
    x1, y1, w1, h1, _ = w.geo
    assert w0 < 0.6 * w1 and h0 < 0.8 * h1, (w0, w1, h0, h1)
    assert abs((x0 + w0 / 2) - (x1 + w1 / 2)) < 1 and abs((y0 + h0 / 2) - (y1 + h1 / 2)) < 1
    w.ap.v = 0.0; w._apply()

    w.show_island(); pump(0.9); assert w.state == "compact"

    # --- Space on the pill opens the notepad (the reported bug)
    assert w.cfg["focus_on_show"] is True and w.get_accept_focus()
    class K:
        def __init__(self, name, state=0): self.state, self.keyval = state, ui.Gdk.keyval_from_name(name)
    assert w._on_key(None, K("space")) is True and w.state == "expanded", "Space did not expand the pill"
    pump(0.9)
    assert w._on_key(None, K("space")) is False                      # in the notepad Space just types
    w.entry.set_text("a b"); assert w.entry.get_text() == "a b"
    w.collapse(); pump(0.6); assert w.state == "compact"
    # click fallback: a pill without keyboard focus opens the notepad on click (Space can't reach it)
    class Click: button = 1
    w.is_active = lambda: False        # no window manager here, so X focus is racy: force "not focused"
    # the idle game is on screen: left click = jump (stays a pill), right click = notepad
    w._on_pill_click(None, Click); assert w.state == "compact" and w.game.manual
    class RClick: button = 3
    w._on_pill_click(None, RClick); assert w.state == "expanded"
    w.collapse(); pump(0.6)
    # game switched off -> the original behaviour: click opens the notepad when the pill has no focus
    w.update_config({"mario_game": False}); pump()
    w._on_pill_click(None, Click); assert w.state == "expanded"
    w.update_config({"mario_game": True})
    del w.is_active
    w.collapse(); pump(0.6); w.expand(); pump(0.9); assert w.state == "expanded"

    # --- add/delete/undo
    w.entry.set_text("smoke task"); w._add(w.entry); pump()
    assert any(t.text == "smoke task" for t in w.store.list_tasks())
    tid = w.store.list_tasks()[0].id
    w._delete(tid); pump(); assert not w.store.list_tasks() and w._undo
    w._undo_delete(); pump(); assert len(w.store.list_tasks()) == 1

    # --- many tasks: list scrolls to the newest one
    for i in range(14):
        w.entry.set_text(f"task number {i}"); w._add(w.entry); pump(0.05)
    w.entry.set_text("the newest task"); w._add(w.entry); pump(0.6)
    adj = w.scroller.get_vadjustment()
    assert adj.get_upper() > adj.get_page_size() + 50
    assert adj.get_value() >= adj.get_upper() - adj.get_page_size() - 2, "did not scroll to newest"
    assert w._hl_row is not None                                   # new row is flashed

    # --- settings live INSIDE the pill (same window, stack page)
    w.show_settings_page(); pump(0.4)
    assert w._page == "settings" and w.stack.get_visible_child_name() == "settings"
    assert w.in_settings and w.get_visible()
    w.update_config({"pill_scale": 1.3, "accent": "#00FF00", "top_margin": 20}); pump()
    assert w.cw == int(216 * 1.3) and w.top == 20
    w.show_notes_page(); assert w._page == "notes"
    w.show_settings_page()
    class E: state = 0; keyval = ui.Gdk.keyval_from_name("Escape")
    assert w._on_key(None, E) and w._page == "notes"                # Esc = back, not collapse
    assert w.state == "expanded"

    # --- settings: sizes are typed numbers; no sliders / +- spinners; wheel never changes a value
    from gi.repository import Gdk
    kinds = []
    def walk(x):
        kinds.append(type(x).__name__)
        if hasattr(x, "get_children"):
            for c in x.get_children(): walk(c)
        elif hasattr(x, "get_child") and x.get_child(): walk(x.get_child())
    walk(w._panel)
    assert "Scale" not in kinds and "SpinButton" not in kinds, kinds
    assert w.cfg["input_border_width"] == 1 and "border: 1px solid" in ui.build_css().decode()
    ent = Gtk.Entry(); ent.set_text("999")
    w._panel._apply_number("input_border_width", ent, 0, 12, True); pump(0.4)
    assert w.cfg["input_border_width"] == 12 and ent.get_text() == "12"             # clamped
    ent.set_text("abc"); w._panel._apply_number("input_border_width", ent, 0, 12, True); pump(0.2)
    assert w.cfg["input_border_width"] == 12 and ent.get_text() == "12"             # bad input ignored
    ent.set_text("4"); w._panel._apply_number("input_border_width", ent, 0, 12, True); pump(0.4)
    assert w.cfg["input_border_width"] == 4 and "border: 4px solid" in ui.build_css().decode()
    combo = [c for c in w._panel.grid.get_children() if type(c).__name__ == "ComboBoxText"][0]
    before = combo.get_active()
    ev = Gdk.Event.new(Gdk.EventType.SCROLL); ev.direction = Gdk.ScrollDirection.DOWN
    combo.emit("scroll-event", ev); pump(0.2)
    assert combo.get_active() == before, "mouse wheel changed a setting"

    # --- glass, theme, notepad size
    from gi.repository import Gdk
    w.update_config({"pill_scale": 1.0, "top_margin": 10, "accent": "#D71921"}); pump()
    assert w.cfg["glass"] is True and ui.PAL["glass"] is True
    assert w.cfg["notepad_scale"] == 0.9 and (w.ew, w.eh) == (396, 450), (w.ew, w.eh)
    w.update_config({"notepad_scale": 1.2}); pump()
    assert (w.ew, w.eh) == (528, 600) and w.win_w > w.ew * 1.1 and w.win_h > w.eh * 1.1
    w.update_config({"notepad_scale": 0.9}); pump()
    w.update_config({"theme": "light"}); pump()
    assert ui.PAL["dark"] is False and ui.PAL["bg"] == "#F4F4F6"
    w.update_config({"theme": "dark", "glass": False}); pump()
    assert ui.PAL["dark"] is True and ui.PAL["glass"] is False and w.get_visible()
    w.update_config({"glass": True, "theme": "auto"}); pump()

    # --- developer info lives in the settings page
    def walk(wd):
        yield wd
        if isinstance(wd, Gtk.Container):
            for c in wd.get_children():
                yield from walk(c)
    uris = {x.get_name()[len("devlink:"):] for x in walk(w._panel)
            if isinstance(x, Gtk.Button) and x.get_name().startswith("devlink:")}
    assert {"mailto:ashishaxm11@gmail.com", "https://github.com/ashishnxt/"} <= uris, uris
    icons = [x.kind for x in walk(w._panel) if type(x).__name__ == "IconArea"]
    assert sorted(icons) == ["code", "mail"]                       # drawn icons, not font glyphs
    assert not any(isinstance(x, Gtk.LinkButton) for x in walk(w._panel))
    texts = {x.get_label() for x in walk(w._panel) if isinstance(x, Gtk.Label)}
    assert "Ashish" in texts and "Developer" in texts and f"v{__version__}" in texts and APP_NAME in texts
    assert w.get_title() == APP_NAME
    w.show_notes_page()

    # --- idle game: shows while the timer is stopped, digits while it runs, can be switched off
    w.collapse(); pump(0.6); assert w.state == "compact"
    assert w.cmp_stack.get_visible_child_name() == "game" and w.game._timer
    w.sw.start(); w._sync_ui()
    assert w.cmp_stack.get_visible_child_name() == "time" and not w.game._timer
    w.sw.pause(); w._sync_ui()
    assert w.cmp_stack.get_visible_child_name() == "game" and w.game._timer
    w.update_config({"mario_game": False}); pump()
    assert w.cmp_stack.get_visible_child_name() == "time" and not w.game._timer
    w.update_config({"mario_game": True}); pump()
    assert w.cmp_stack.get_visible_child_name() == "game"
    w.game.world.reset(); pump(0.2)
    class Up: state = 0; keyval = Gdk.keyval_from_name("Up")
    assert w._on_key(None, Up) and w.game.manual                   # Up jumps and takes control
    class Sp: state = 0; keyval = Gdk.keyval_from_name("space")
    assert w._on_key(None, Sp) and w.state == "expanded"           # Space still opens the notepad
    w.collapse(); pump(0.6)
    w.update_config({"game_theme": "pill"}); pump(0.2); w.update_config({"game_theme": "mario"})
    w.expand(); pump(0.6)

    def walk(wd):
        yield wd
        if isinstance(wd, Gtk.Container):
            for c in wd.get_children():
                yield from walk(c)
    # --- notepad layout: four task rows visible at once at the default size, list wider than the header
    w.update_config({"notepad_scale": 0.9}); pump(0.3)
    w.state = "expanded"; w.expand(); pump(0.4)
    for i in range(6):
        w.entry.set_text(f"layout row {i}"); w._add(w.entry); pump(0.05)
    w.ex.a = w.ap.a = None; w.ex.v = w.ap.v = 1.0; w._apply(); pump(0.6)
    row_h = next(walk(w.list)).get_allocated_height() or 40
    rows = [x for x in walk(w.list) if isinstance(x, Gtk.ListBoxRow)]
    row_h = rows[0].get_allocated_height()
    view_h = w.scroller.get_vadjustment().get_page_size()
    assert view_h >= 4 * row_h - 2, (view_h, row_h)                 # room for 4 tasks
    assert w.scroller.get_allocated_width() >= w.display.get_allocated_width() + 20   # wider than the display block
    assert w.display.get_allocated_height() <= 7 * (w.ew - 52) / 39 + 30            # no dead space under the dots

    # --- input follows the pill border colour and has its own size setting
    w.update_config({"border_color": "#3366FF", "input_scale": 0.85, "input_border_width": 3}); pump()
    css = ui.build_css().decode()
    assert "border: 3px solid #3366FF" in css and "caret-color: #3366FF" in css, css[css.find("entry.addtask"):][:300]
    small = css[css.find("entry.addtask"):][:420]
    w.update_config({"input_scale": 1.3}); pump()
    big = ui.build_css().decode()
    assert big != css and "font-size: 15.6pt" in big and "font-size: 10.2pt" in small
    w.update_config({"border_color": "#D71921", "input_scale": 0.85, "input_border_width": 1}); pump()

    # --- per-task button: play icon, then pause icon while that task is being timed
    def play_labels():
        return [x.get_label() for x in walk(w.list) if isinstance(x, Gtk.Button) and x.get_label() in ("▶", "❚❚")]
    w.state = "expanded"; w.refresh_tasks(); pump(0.2)
    first = w.store.list_tasks()[0].id
    labels = play_labels(); assert labels and set(labels) == {"▶"}, labels
    w._start_task(first); pump(0.3)
    labels = play_labels(); assert labels[0] == "❚❚" and set(labels[1:]) <= {"▶"} and w.sw.running, labels
    w._start_task(first); pump(0.3)                                   # same button again = pause
    assert not w.sw.running and set(play_labels()) == {"▶"}
    assert "^t-" not in w.store.path.read_text()                      # nothing hidden in the note

    # --- idle cost: timers exist only while the pill is on screen
    w.update_config({"auto_hide_seconds": 30}); pump(0.2)
    assert w._tick_id and w._ah_id, (w._tick_id, w._ah_id)
    assert w._really_visible()

    # --- identical refreshes do not rebuild the rows; huge notes are capped
    rows = w.list.get_children(); w.refresh_tasks(); assert w.list.get_children() == rows
    note = w.store.path
    note.write_text("# T\\n" + "".join(f"- [ ] bulk {i}\\n" for i in range(450)))
    w.refresh_tasks(); pump(0.3)
    kids = w.list.get_children()
    assert len(kids) == ui.MAX_ROWS + 1 and "250 older" in kids[0].get_child().get_text()
    note.write_text("# T\\n- [ ] one\\n- [ ] two\\n"); w.refresh_tasks(); pump(0.2)

    # --- a message makes room in the header (no cut-off text next to UNDO)
    w._toast("DELETED", undo=True); assert w.head_lbl.get_text().strip() in ("○", "●"), w.head_lbl.get_text()
    w._clear_toast(); assert "TIMER" in w.head_lbl.get_text()

    # --- Ctrl+S opens the settings page (from the pill and from the notepad); again = back
    w.show_notes_page(); pump(0.3)
    class CtrlS: state = Gdk.ModifierType.CONTROL_MASK; keyval = Gdk.keyval_from_name("s")
    assert w._on_key(None, CtrlS) and w._page == "settings"
    assert w._on_key(None, CtrlS) and w._page == "notes"
    w.collapse(); pump(0.6); assert w.state == "compact"
    assert w._on_key(None, CtrlS) and w.state == "expanded" and w._page == "settings"
    w.show_notes_page(); pump(0.4)

    # --- click a task: its complete text slides in; actions work; Esc slides back
    full = "ZZZ " + "a long task that does not fit on one line of the list " * 6
    w.store.add_task(full); w.refresh_tasks(scroll_end=True); pump(0.4)
    row = next(r for r in w.list.get_children() if r.get_name() in w._tasks_by_id
               and w._tasks_by_id[r.get_name()].text.startswith("ZZZ"))
    assert row.get_activatable() and row.get_name().startswith("t-")
    w.list.emit("row-activated", row); pump(0.5)
    assert w._page == "detail" and w.stack.get_visible_child_name() == "detail" and w.in_subpage
    assert w.stack.get_transition_type() == Gtk.StackTransitionType.SLIDE_LEFT
    assert w._detail.text.get_text() == full.strip()                       # the complete text, not an ellipsis
    assert w.exp_box.get_allocated_width() == w.ew                         # the page never widens the frame
    w._detail._on_timer(); pump(0.3)
    assert w.sw.running and w._detail.btn_timer.get_label() == "PAUSE"
    w._detail._on_timer(); pump(0.3)
    assert not w.sw.running and w._detail.btn_timer.get_label() == "START"
    w._detail._on_done(); pump(0.3)
    assert w._detail.status_chip.get_text() == "DONE" and w._detail.btn_done.get_label() == "REOPEN"
    w._detail._on_done(); pump(0.3); assert w._detail.status_chip.get_text() == "OPEN"
    w.update_config({"auto_hide_seconds": 1}); w._last_input -= 30; w._autohide_check()
    assert w.state == "expanded", "must not auto-hide while a task is being read"
    w.update_config({"auto_hide_seconds": 0})
    class Esc: state = 0; keyval = Gdk.keyval_from_name("Escape")
    assert w._on_key(None, Esc) and w._page == "notes"
    assert w.stack.get_transition_type() == Gtk.StackTransitionType.SLIDE_RIGHT
    w.list.emit("row-activated", row); pump(0.4)
    w._detail._on_delete(); pump(0.4)                                      # delete from the detail page
    assert w._page == "notes" and w._undo and not any(t.text.startswith("ZZZ") for t in w.store.list_tasks())
    w._undo_delete(); pump(0.3)
    assert any(t.text.startswith("ZZZ") for t in w.store.list_tasks())

    # --- hide converges
    w.hide_island(); pump(0.8); assert w.state == "hidden" and not w.get_visible()
    assert w._tick_id == 0 and w._ah_id == 0 and w.game._timer == 0       # nothing wakes up while hidden
    print("SMOKE_OK")
""")


def test_widget_smoke(env):
    e = dict(os.environ, XDG_CONFIG_HOME=str(env / "cfg2"), XDG_STATE_HOME=str(env / "state2"))
    (env / "cfg2" / "nothing-tasks").mkdir(parents=True)
    (env / "cfg2" / "nothing-tasks" / "config.json").write_text(
        '{"vault": "%s", "note": "smoke.md", "auto_hide_seconds": 0, "auto_shortcut": false}' % (env / "vault"))
    r = subprocess.run(["xvfb-run", "-a", sys.executable, "-c", SCRIPT], env=e, timeout=90,
                       capture_output=True, text=True, check=False,
                       cwd=os.path.dirname(os.path.dirname(__file__)))
    assert "SMOKE_OK" in r.stdout, r.stdout + r.stderr
