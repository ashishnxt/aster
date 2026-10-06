import multiprocessing as mp
import time

import pytest

from nothing_tasks import core
from nothing_tasks.core import Stopwatch, VaultError, VaultStore, clean_task_text, fmt_hms, sanitize_config


# ---------------------------------------------------------------- store
def test_store_roundtrip(env):
    v = env / "vault"
    (v / "Widget Tasks.md").write_text("# Mine\n\nsome prose\n- [ ] made in obsidian\n")
    s = VaultStore(str(v), "Widget Tasks.md")
    a = s.add_task("write docs #work")
    tasks = s.list_tasks()
    assert [t.text for t in tasks] == ["made in obsidian", "write docs #work"]
    assert all(t.id.startswith("t-") for t in tasks)
    s.add_time(a.id, 65)
    s.set_done(a.id, True)
    body = (v / "Widget Tasks.md").read_text()
    assert "some prose" in body
    assert "- [x] write docs #work ⏱ 00:01:05\n" in body or body.rstrip().endswith("- [x] write docs #work ⏱ 00:01:05")
    assert "^t-" not in body                                      # no id is ever written into the note
    t = next(x for x in s.list_tasks() if x.id == a.id)
    assert t.done and t.seconds == 65


def test_delete_and_restore(env):
    s = VaultStore(str(env / "vault"), "n.md")
    a, _b = s.add_task("one"), s.add_task("two")
    removed = s.delete_task(a.id)
    assert removed and not s.delete_task(a.id)
    assert [t.text for t in s.list_tasks()] == ["two"]
    s.restore(*removed)
    assert [t.text for t in s.list_tasks()] == ["one", "two"]


def test_crlf_preserved(env):
    p = env / "vault" / "n.md"
    p.write_bytes(b"# T\r\n- [ ] a ^t-aaaaaa\r\n")
    s = VaultStore(str(env / "vault"), "n.md")
    s.add_task("b")
    raw = p.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n") and b"\r\n" in raw


def test_note_cannot_escape_vault(env):
    with pytest.raises(VaultError):
        VaultStore(str(env / "vault"), "../evil.md")


def test_text_sanitised():
    assert clean_task_text("a\nb   c ⏱ 00:00:09 ^t-abcdef") == "a b c"
    assert len(clean_task_text("x" * 900)) == core.MAX_TASK_LEN
    with pytest.raises(VaultError):
        VaultStore.add_task(VaultStore("/tmp", "x"), "   ")


def test_backup_created_once(env):
    v = env / "vault"
    (v / "n.md").write_text("- [ ] a ^t-aaaaaa\n")
    s = VaultStore(str(v), "n.md")
    s.add_task("b"); s.add_task("c")
    assert len(list((env / "state" / "backups").glob("*.bak"))) == 1


def test_unwritable_vault_raises_friendly_error(env):
    s = VaultStore("/proc/definitely/not/writable", "n.md")
    with pytest.raises(VaultError):
        s.add_task("x")


def _worker(args):
    vault, i = args
    VaultStore(vault, "n.md").add_task(f"task {i}")


def test_concurrent_writers_do_not_lose_tasks(env):
    vault = str(env / "vault")
    with mp.Pool(4) as pool:
        pool.map(_worker, [(vault, i) for i in range(24)])
    assert len(VaultStore(vault, "n.md").list_tasks()) == 24


# ---------------------------------------------------------------- config
def test_config_sanitised():
    c = sanitize_config({"top_margin": 9999, "pill_scale": "big", "accent": "red",
                         "monitor": "moon", "animations": "yes", "border_color": "#abcdef",
                         "auto_hide_seconds": -5, "bogus": 1})
    assert c["top_margin"] == 80 and c["pill_scale"] == core.DEFAULT_CONFIG["pill_scale"] and c["accent"] == "#D71921"
    assert c["monitor"] == "pointer" and c["animations"] is True
    assert c["border_color"] == "#ABCDEF" and c["auto_hide_seconds"] == 0 and "bogus" not in c


def test_config_migrates_old_key():
    assert sanitize_config({"keep_visible_when_running": True})["auto_hide_when_running"] is False


def test_config_save_load_and_corrupt(env):
    core.save_config({"accent": "#112233", "vault": str(env)})
    assert core.load_config()["accent"] == "#112233"
    core.CONFIG_FILE.write_text("{ not json")
    assert core.load_config()["accent"] == "#D71921"
    assert core.CONFIG_FILE.with_suffix(".corrupt").exists()


# ---------------------------------------------------------------- stopwatch
def test_stopwatch_survives_restart(env):
    sw = Stopwatch(); sw.start("t-aaaaaa"); time.sleep(1.1)
    sw2 = Stopwatch()
    assert sw2.running and sw2.elapsed >= 1
    tid, delta = sw2.pause()
    assert tid == "t-aaaaaa" and delta >= 1 and sw2.pause()[1] == 0


def test_switch_commits_old_task(env):
    sw = Stopwatch()
    sw.start("t-aaaaaa"); sw.accumulated, sw.running = 30, False
    assert sw.switch("t-bbbbbb") == ("t-aaaaaa", 30)
    assert sw.task_id == "t-bbbbbb" and sw.running


def test_detach_and_external_reload(env):
    a, b = Stopwatch(), Stopwatch()
    a.start("t-aaaaaa")
    assert b.reload_if_changed() and b.running        # other process saw the change
    a.detach()
    assert b.reload_if_changed() and not b.running and b.task_id is None


def test_clock_jump_backwards_is_safe(env):
    sw = Stopwatch(); sw.start("t-aaaaaa"); sw.started_at = time.time() + 3600
    assert sw.elapsed == 0


def test_fmt():
    assert fmt_hms(3725) == "01:02:05"


def test_default_shortcut_is_alt_x_and_old_defaults_migrate():
    assert core.DEFAULT_CONFIG["shortcut"] == "<Alt>x"
    assert sanitize_config({"shortcut": "<Ctrl>x"})["shortcut"] == "<Alt>x"              # 1.2.2 default -> Alt+X
    assert sanitize_config({"shortcut": "<Ctrl>x", "config_version": 6})["shortcut"] == "<Alt>x"   # saved by 1.2.2
    assert sanitize_config({"shortcut": "<alt>x", "config_version": 5})["shortcut"] == "<Alt>x"    # the author's file
    assert sanitize_config({"shortcut": "<Ctrl>x", "config_version": 7})["shortcut"] == "<Ctrl>x"  # chosen on purpose
    assert sanitize_config({"shortcut": "<Ctrl><Alt>n"})["shortcut"] == "<Ctrl><Alt>n"   # custom kept
    assert sanitize_config({"shortcut": "<control>X", "config_version": 7})["shortcut"] == "<Ctrl>x"
    assert core.DEFAULT_CONFIG["config_version"] == 7


def test_users_own_config_json_is_the_default():
    """The values the author asked for, key by key (vault = ~/Obsidian, i.e. /home/ashishp/Obsidian for him)."""
    mine = {"note": "Widget Tasks.md", "accent": "#D71921", "border_color": "#77767B", "border_width": 1.0,
            "input_border_width": 1, "input_scale": 0.85, "input_width": 100, "top_margin": 10, "pill_scale": 1.2,
            "auto_hide_seconds": 3, "auto_hide_when_running": True, "collapse_on_blur": True,
            "focus_on_show": True, "animations": True, "animation_speed": 1.0, "show_seconds_strip": True,
            "monitor": "pointer", "shortcut": "<Alt>x", "auto_shortcut": False, "glass": True,
            "glass_strength": 55, "glass_blur": True, "theme": "auto", "notepad_scale": 0.9,
            "mario_game": True, "game_theme": "pill", "config_version": 7, "log_level": "INFO"}
    d = core.DEFAULT_CONFIG
    for k, v in mine.items():
        assert d[k] == v, (k, d[k], v)
    assert d["vault"] == str(core.Path.home() / "Obsidian")
    assert set(d) == set(mine) | {"vault"}                       # nothing else sneaks in
    assert core.sanitize_config(dict(mine, vault="/home/ashishp/Obsidian")) == dict(mine, vault="/home/ashishp/Obsidian")


def test_existing_saved_values_are_never_overwritten_by_new_defaults():
    saved = {"border_color": "#D71921", "pill_scale": 1.0, "game_theme": "mario", "auto_shortcut": True,
             "vault": "/data/vault", "config_version": 7}
    c = sanitize_config(saved)
    assert (c["border_color"], c["pill_scale"], c["game_theme"], c["auto_shortcut"], c["vault"]) == \
        ("#D71921", 1.0, "mario", True, "/data/vault")


def test_new_glass_theme_game_settings():
    d = core.DEFAULT_CONFIG
    assert d["glass"] is True and d["glass_strength"] == 55 and d["glass_blur"] is True
    assert d["theme"] == "auto" and d["notepad_scale"] == 0.9
    assert d["mario_game"] is True and d["game_theme"] == "pill"
    c = sanitize_config({"glass_strength": 500, "notepad_scale": 9, "theme": "neon", "game_theme": "x",
                         "mario_game": "yes"})
    assert c["glass_strength"] == 100 and c["notepad_scale"] == 1.2 and c["theme"] == "auto"
    assert c["game_theme"] == "pill" and c["mario_game"] is True        # invalid -> the default
    assert sanitize_config({"game_theme": "mario"})["game_theme"] == "mario"
    assert sanitize_config({"notepad_scale": 0.1})["notepad_scale"] == 0.7
    assert sanitize_config({"theme": "light", "game_theme": "pill"})["game_theme"] == "pill"


def test_v4_defaults_and_migration():
    d = core.DEFAULT_CONFIG
    assert d["input_border_width"] == 1 and d["focus_on_show"] is True      # Space needs keyboard focus
    assert sanitize_config({"input_border_width": 99})["input_border_width"] == 12      # clamped
    assert sanitize_config({"input_border_width": -3})["input_border_width"] == 0
    # 1.1.1 defaults are replaced once ...
    old = {"config_version": 3, "focus_on_show": False, "input_border_width": 10}
    assert sanitize_config(old)["focus_on_show"] is True and sanitize_config(old)["input_border_width"] == 1
    # ... but values chosen on purpose in the current version are kept
    new = {"config_version": 4, "focus_on_show": False, "input_border_width": 10}
    assert sanitize_config(new)["focus_on_show"] is False and sanitize_config(new)["input_border_width"] == 10
    assert sanitize_config({"input_border_width": 4})["input_border_width"] == 4         # custom value kept


# ---------------------------------------------------------------- ids are never written into the note
def test_note_has_no_hidden_ids_and_ids_stay_stable(env):
    s = VaultStore(str(env / "vault"), "n.md")
    a = s.add_task("buy milk")
    body = (env / "vault" / "n.md").read_text()
    assert "^t-" not in body and body.rstrip().endswith("- [ ] buy milk")
    assert s.list_tasks()[0].id == a.id
    s.add_time(a.id, 90)
    s.set_done(a.id, True)
    assert s.list_tasks()[0].id == a.id                           # time / done do not change the id
    assert "^t-" not in (env / "vault" / "n.md").read_text()


def test_duplicate_texts_get_distinct_ids(env):
    s = VaultStore(str(env / "vault"), "n.md")
    a, b = s.add_task("same"), s.add_task("same")
    assert a.id != b.id and {t.id for t in s.list_tasks()} == {a.id, b.id}
    s.set_done(b.id, True)
    assert [t.done for t in s.list_tasks()] == [False, True]


def test_legacy_ids_are_stripped_once_and_the_timer_follows(env):
    p = env / "vault" / "n.md"
    p.write_text("# T\n- [ ] fix ssl ⏱ 00:00:05 ^t-2088de\n- [x] done thing ^t-abcdef\nprose ^t-123456\n")
    sw = Stopwatch()
    sw.start("t-2088de")
    s = VaultStore(str(env / "vault"), "n.md")
    tasks = s.list_tasks()
    body = p.read_text()
    assert "^t-2088de" not in body and "^t-abcdef" not in body
    assert "- [ ] fix ssl ⏱ 00:00:05\n" in body and "prose ^t-123456" in body    # only task lines touched
    assert [t.text for t in tasks] == ["fix ssl", "done thing"] and tasks[0].seconds == 5
    s.migrate_timer(sw)
    assert sw.task_id == tasks[0].id                              # the running timer now points at the new id
    assert len(list((env / "state" / "backups").glob("*.bak"))) == 1


def test_editing_a_task_in_obsidian_drops_the_old_id(env):
    p = env / "vault" / "n.md"
    s = VaultStore(str(env / "vault"), "n.md")
    a = s.add_task("original")
    p.write_text(p.read_text().replace("original", "reworded"))
    assert s.add_time(a.id, 5) is None                            # old id no longer exists
    assert s.list_tasks()[0].id != a.id


def test_input_scale_setting():
    d = core.DEFAULT_CONFIG
    assert d["input_scale"] == 0.85
    assert sanitize_config({"input_scale": 5})["input_scale"] == 1.4
    assert sanitize_config({"input_scale": 0.1})["input_scale"] == 0.6
