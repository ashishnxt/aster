"""Core logic: validated config, crash-safe Obsidian task store, persistent stopwatch.

No GTK imports, so the widget, the CLI and the MCP server all share it.
Python 3.10+.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import logging.handlers
import os
import re
import shutil
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("nothing_tasks")

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "nothing-tasks"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "nothing-tasks"
CONFIG_FILE = CONFIG_DIR / "config.json"
TIMER_FILE = STATE_DIR / "timer.json"
LOG_FILE = STATE_DIR / "app.log"
MAX_TASK_LEN = 500


# ---------------------------------------------------------------- logging
def setup_logging(level: str = "INFO", console: bool = True) -> None:
    log.setLevel(getattr(logging, level, logging.INFO))
    if log.handlers:
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(LOG_FILE, maxBytes=256_000, backupCount=2)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError:
        pass
    if console:
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        log.addHandler(sh)


def atomic_write(path: Path, data: str | bytes) -> None:
    """Write via temp file + fsync + rename: readers never see a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = data.encode("utf-8") if isinstance(data, str) else data
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------- config
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_MOD_NAMES = {"ctrl": "Ctrl", "control": "Ctrl", "primary": "Ctrl", "alt": "Alt", "mod1": "Alt",
              "super": "Super", "mod4": "Super", "shift": "Shift"}


def normalize_binding(binding: str) -> str:
    """'<alt>x' -> '<Alt>x', '<control>X' -> '<Ctrl>x' (single letters are lower-cased)."""
    mods = [_MOD_NAMES.get(m.lower(), m) for m in re.findall(r"<(\w+)>", binding)]
    key = re.sub(r"<\w+>", "", binding).strip()
    return "".join(f"<{m}>" for m in mods) + (key.lower() if len(key) == 1 else key)


# key: (default, kind, lo, hi)   kind = bool|int|float|color|str|binding|<tuple of allowed>
SPEC = {
    "vault": (str(Path.home() / "Obsidian"), "str", None, None),
    "note": ("Widget Tasks.md", "str", None, None),
    "accent": ("#D71921", "color", None, None),
    "border_color": ("#77767B", "color", None, None),   # pill outline (red by default)
    "border_width": (1.0, "float", 0.0, 4.0),
    "input_border_width": (1, "int", 0, 12),            # red outline of the "Add a task" input, px
    "input_scale": (0.85, "float", 0.6, 1.4),             # size of the "add a task" box
    "input_width": (100, "int", 50, 100),                 # its width, % of the task list (100 = same width)
    "top_margin": (10, "int", 0, 80),
    "pill_scale": (1.2, "float", 0.7, 1.5),
    "auto_hide_seconds": (3, "int", 0, 600),           # 0 = never
    "auto_hide_when_running": (True, "bool", None, None),
    "collapse_on_blur": (True, "bool", None, None),
    "focus_on_show": (True, "bool", None, None),        # True: the pill takes keyboard focus, so Space/Enter/Esc work
    "animations": (True, "bool", None, None),
    "animation_speed": (1.0, "float", 0.5, 2.0),
    "show_seconds_strip": (True, "bool", None, None),
    "monitor": ("pointer", ("pointer", "primary"), None, None),
    "shortcut": ("<Alt>x", "binding", None, None),         # toggles (opens AND closes) the pill
    "auto_shortcut": (False, "bool", None, None),        # register that shortcut with GNOME automatically
    "glass": (True, "bool", None, None),                 # frosted-glass pill
    "glass_strength": (55, "int", 0, 100),               # 0 = solid, 100 = most see-through
    "glass_blur": (True, "bool", None, None),            # best effort: blur what is behind (X11 only)
    "theme": ("auto", ("auto", "dark", "light"), None, None),   # auto = follow the system
    "notepad_scale": (0.9, "float", 0.7, 1.2),           # size of the expanded notepad
    "mario_game": (True, "bool", None, None),            # idle game in the pill while the timer is stopped
    "game_theme": ("pill", ("mario", "pill"), None, None),
    "config_version": (7, "int", 1, 99),
    "log_level": ("INFO", ("DEBUG", "INFO", "WARNING", "ERROR"), None, None),
}
DEFAULT_CONFIG = {k: v[0] for k, v in SPEC.items()}


def sanitize_config(raw: dict) -> dict:
    """Coerce/clamp every known key; unknown or invalid values fall back to defaults."""
    cfg = dict(DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        return cfg
    if "keep_visible_when_running" in raw and "auto_hide_when_running" not in raw:   # v0 migration
        raw = {**raw, "auto_hide_when_running": not raw["keep_visible_when_running"]}
    if raw.get("config_version", 1) < 2 and raw.get("shortcut") == "<Super>t":     # v1 default -> v2 default
        raw = {k: v for k, v in raw.items() if k != "shortcut"}
    if raw.get("config_version", 1) < 4:           # 1.1.1 defaults (no keyboard focus, 10 px input border)
        stale = {k for k, v in (("focus_on_show", False), ("input_border_width", 10)) if raw.get(k) == v}
        raw = {k: v for k, v in raw.items() if k not in stale}
    if raw.get("config_version", 1) < 7 and isinstance(raw.get("shortcut"), str) \
            and normalize_binding(raw["shortcut"]) in ("<Alt>x", "<Ctrl>x"):
        raw = {k: v for k, v in raw.items() if k != "shortcut"}     # 1.2.x defaults -> the current default (Alt+X)
    for key, (_d, kind, lo, hi) in SPEC.items():
        if key not in raw:
            continue
        v, ok, val = raw[key], False, None
        try:
            if kind == "bool":
                ok, val = isinstance(v, bool), v
            elif kind in ("int", "float"):
                ok = isinstance(v, (int, float)) and not isinstance(v, bool)
                if ok:
                    val = min(hi, max(lo, int(v) if kind == "int" else float(v)))
            elif kind == "color":
                ok = isinstance(v, str) and bool(HEX.match(v))
                val = v.upper() if ok else None
            elif kind == "str":
                ok, val = isinstance(v, str) and v.strip() != "", (v.strip() if isinstance(v, str) else v)
            elif kind == "binding":
                ok = isinstance(v, str) and bool(re.sub(r"<\w+>", "", v).strip())
                val = normalize_binding(v) if ok else None
            else:
                ok, val = v in kind, v
        except (TypeError, ValueError):
            ok = False
        if ok:
            cfg[key] = val
        else:
            log.warning("config: invalid value for %r -> using default", key)
    cfg["config_version"] = SPEC["config_version"][0]
    return cfg


def load_config() -> dict:
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        cfg = dict(DEFAULT_CONFIG)
        try:
            save_config(cfg)
        except OSError as e:
            log.warning("cannot write default config: %s", e)
        return cfg
    except (OSError, ValueError) as e:
        log.error("config unreadable (%s); keeping a copy and using defaults", e)
        try:
            shutil.copy2(CONFIG_FILE, CONFIG_FILE.with_suffix(".corrupt"))
        except OSError:
            pass
        return dict(DEFAULT_CONFIG)
    return sanitize_config(raw)


def save_config(cfg: dict) -> None:
    atomic_write(CONFIG_FILE, json.dumps(sanitize_config(cfg), indent=2) + "\n")


# ---------------------------------------------------------------- time helpers
def fmt_hms(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def parse_hms(text: str) -> int:
    h, m, s = (int(p) for p in text.split(":"))
    return h * 3600 + m * 60 + s


# ---------------------------------------------------------------- tasks
# "- [ ] Fix SSL config #work ⏱ 00:42:10 ^t-a1b2c3"
TASK_RE = re.compile(
    r"^(?P<indent>\s*)- \[(?P<mark>[ xX])\] (?P<text>.*?)"
    r"(?: ⏱ (?P<time>\d+:\d\d:\d\d))?"
    r"(?: \^(?P<id>t-[0-9a-f]{6}))?\s*$"
)
def task_ident(text: str, nth: int) -> str:
    """Stable id derived from the task text (no id is ever written into the note).
    Identical texts are told apart by their order: t-ab12cd, t-ab12cd.1, ..."""
    return f"t-{hashlib.sha1(text.encode('utf-8')).hexdigest()[:6]}" + (f".{nth}" if nth else "")


def _iter_tasks(lines):
    """Yield (line_index, regex_match, ident) for every task line."""
    seen: dict[str, int] = {}
    for i, line in enumerate(lines):
        m = TASK_RE.match(line)
        if not m:
            continue
        text = m["text"].strip()
        n = seen.get(text, 0)
        seen[text] = n + 1
        yield i, m, task_ident(text, n)


_TRAILING_META = re.compile(r"(?:\s+(?:⏱ \d+:\d\d:\d\d|\^t-[0-9a-f]{6}))+\s*$")


class VaultError(Exception):
    """User-presentable problem with the vault / note file."""


@dataclass
class Task:
    id: str
    text: str
    done: bool = False
    seconds: int = 0


def clean_task_text(text: str) -> str:
    text = " ".join(str(text).split())                  # no newlines / runs of spaces
    text = _TRAILING_META.sub("", text).strip()         # can't spoof our own metadata
    return text[:MAX_TASK_LEN]


class VaultStore:
    """Reads/writes tasks in one markdown note. Only task lines are touched; every
    other byte is preserved (incl. CRLF line endings). Writes are atomic, serialized
    with a file lock (widget + MCP server can run together) and backed up once per run."""

    def __init__(self, vault: str, note: str):
        root = Path(vault).expanduser()
        note = note if note.lower().endswith(".md") else note + ".md"
        path = root / note
        try:
            path.resolve().relative_to(root.resolve())
        except ValueError:
            raise VaultError("Note path must stay inside the vault") from None
        self.path = path
        digest = hashlib.sha1(str(path).encode()).hexdigest()[:16]
        self._lock_path = STATE_DIR / "locks" / f"{digest}.lock"
        self._backed_up = False

    # -- plumbing
    @contextmanager
    def _locked(self):
        try:
            self._lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as e:
            raise VaultError(f"Cannot create lock file: {e.strerror}") from e
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self) -> tuple[list[str], str]:
        try:
            text = self.path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            return ["# Widget Tasks", ""], "\n"
        except UnicodeDecodeError:
            raise VaultError(f"{self.path.name} is not valid UTF-8") from None
        except OSError as e:
            raise VaultError(f"Cannot read note: {e.strerror}") from e
        nl = "\r\n" if "\r\n" in text else "\n"
        return text.split(nl), nl

    def _backup(self) -> None:
        if self._backed_up:
            return
        self._backed_up = True
        try:
            if not self.path.exists():
                return
            d = STATE_DIR / "backups"
            d.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, d / f"{self.path.stem}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
            for old in sorted(d.glob("*.bak"), key=lambda p: p.stat().st_mtime)[:-10]:
                old.unlink(missing_ok=True)
        except OSError as e:
            log.warning("backup failed: %s", e)

    def _write(self, lines: list[str], nl: str) -> None:
        self._backup()
        try:
            atomic_write(self.path, nl.join(lines))
        except OSError as e:
            raise VaultError(f"Cannot write note: {e.strerror}") from e

    @staticmethod
    def _render(t: Task, indent: str = "") -> str:
        tm = f" ⏱ {fmt_hms(t.seconds)}" if t.seconds else ""
        return f"{indent}- [{'x' if t.done else ' '}] {t.text}{tm}"      # nothing hidden, nothing extra

    @staticmethod
    def _parse(m, ident: str) -> Task:
        return Task(ident, m["text"].strip(), m["mark"] != " ", parse_hms(m["time"]) if m["time"] else 0)

    # -- legacy ^t-xxxxxx block ids (older versions wrote them at the end of every task line)
    @staticmethod
    def _legacy_file() -> Path:
        return STATE_DIR / "legacy_ids.json"

    def _remember_legacy(self, mapping: dict) -> None:
        try:
            try:
                old = json.loads(self._legacy_file().read_text())
            except (OSError, ValueError):
                old = {}
            atomic_write(self._legacy_file(), json.dumps({**old, **mapping}))
        except OSError as e:
            log.warning("cannot record id migration: %s", e)

    def migrate_timer(self, sw: Stopwatch) -> None:
        """If the running timer points at a task by its old ^t- id, point it at the new id."""
        try:
            mapping = json.loads(self._legacy_file().read_text())
        except (OSError, ValueError):
            return
        if sw.task_id in mapping:
            sw.retarget(mapping[sw.task_id])

    # -- api
    def list_tasks(self) -> list[Task]:
        """Parse all tasks. A leftover ^t-xxxxxx id from older versions is removed (once)."""
        with self._locked():
            lines, nl = self._read()
            tasks, legacy = [], {}
            for i, m, ident in _iter_tasks(lines):
                t = self._parse(m, ident)
                tasks.append(t)
                if m["id"]:
                    legacy[m["id"]] = ident
                    lines[i] = self._render(t, m["indent"])
            if legacy:
                self._write(lines, nl)
                self._remember_legacy(legacy)
                log.info("removed %d legacy task ids from %s", len(legacy), self.path.name)
            return tasks

    def add_task(self, text: str) -> Task:
        text = clean_task_text(text)
        if not text:
            raise VaultError("Task text is empty")
        with self._locked():
            lines, nl = self._read()
            same = sum(1 for _i, m, _id in _iter_tasks(lines) if m["text"].strip() == text)
            t = Task(task_ident(text, same), text)
            while lines and lines[-1] == "":
                lines.pop()
            self._write(lines + [self._render(t), ""], nl)
        return t

    def _update(self, task_id: str, fn) -> Task | None:
        with self._locked():
            lines, nl = self._read()
            for i, m, ident in _iter_tasks(lines):
                if ident == task_id:
                    t = self._parse(m, ident)
                    fn(t)
                    lines[i] = self._render(t, m["indent"])
                    self._write(lines, nl)
                    return t
        return None

    def set_done(self, task_id: str, done: bool) -> Task | None:
        return self._update(task_id, lambda t: setattr(t, "done", done))

    def add_time(self, task_id: str, seconds: int) -> Task | None:
        return self._update(task_id, lambda t: setattr(t, "seconds", t.seconds + int(seconds)))

    def delete_task(self, task_id: str) -> tuple[int, str] | None:
        """Remove a task; returns (line_index, raw_line) so the caller can offer undo."""
        with self._locked():
            lines, nl = self._read()
            for i, _m, ident in _iter_tasks(lines):
                if ident == task_id:
                    raw = lines.pop(i)
                    self._write(lines, nl)
                    return i, raw
        return None

    def restore(self, index: int, line: str) -> None:
        with self._locked():
            lines, nl = self._read()
            lines.insert(min(index, len(lines)), line)
            self._write(lines, nl)


# ---------------------------------------------------------------- stopwatch
class Stopwatch:
    """Wall-clock based, so it survives restarts/reboots: we persist the start
    timestamp, never a running counter. State lives in a small JSON file that the
    widget and the MCP server share."""

    KEYS = ("task_id", "running", "started_at", "accumulated", "committed")

    def __init__(self, path: Path | None = None):
        self.path = path or TIMER_FILE
        self.task_id: str | None = None
        self.running = False
        self.started_at = 0.0
        self.accumulated = 0.0    # session seconds up to the last pause
        self.committed = 0.0      # part of the session already saved to the task
        self._mtime = 0.0
        self.refresh()

    def refresh(self) -> None:
        try:
            d = json.loads(self.path.read_text())
            for k in self.KEYS:
                setattr(self, k, d[k])
            self._mtime = self.path.stat().st_mtime
        except (OSError, ValueError, KeyError):
            pass

    def reload_if_changed(self) -> bool:
        """True if another process (e.g. the MCP server) changed the timer."""
        try:
            m = self.path.stat().st_mtime
        except OSError:
            return False
        if m != self._mtime:
            self.refresh()
            return True
        return False

    def _save(self) -> None:
        try:
            atomic_write(self.path, json.dumps({k: getattr(self, k) for k in self.KEYS}))
            self._mtime = self.path.stat().st_mtime
        except OSError as e:
            log.error("cannot save timer state: %s", e)

    @property
    def elapsed(self) -> float:
        extra = max(0.0, time.time() - self.started_at) if self.running else 0.0   # clock-jump safe
        return self.accumulated + extra

    def snapshot(self) -> dict:
        return {"running": self.running, "task_id": self.task_id,
                "elapsed_seconds": int(self.elapsed), "elapsed": fmt_hms(self.elapsed)}

    def start(self, task_id: str | None = None) -> None:
        if task_id is not None:
            self.task_id = task_id
        if not self.running:
            self.running, self.started_at = True, time.time()
            self._save()

    def pause(self) -> tuple[str | None, int]:
        """Pause; returns (task_id, uncommitted_seconds) for the caller to save."""
        if self.running:
            self.accumulated = self.elapsed
            self.running = False
        delta = int(self.accumulated - self.committed)
        if delta > 0:
            self.committed += delta
        self._save()
        return self.task_id, max(delta, 0)

    def reset(self) -> tuple[str | None, int]:
        out = self.pause()
        self.accumulated = self.committed = 0.0
        self._save()
        return out

    def retarget(self, task_id: str) -> None:
        self.task_id = task_id
        self._save()

    def detach(self) -> None:
        """Forget the current task and session (used when the task is deleted)."""
        self.running = False
        self.accumulated = self.committed = 0.0
        self.task_id = None
        self._save()

    def switch(self, task_id: str) -> tuple[str | None, int]:
        """Move to another task: commit the old session, start a new one."""
        out = self.reset()
        self.start(task_id)
        return out
