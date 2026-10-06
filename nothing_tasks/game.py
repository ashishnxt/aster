"""The idle game shown in the pill while the stopwatch is not running.

RunnerWorld  - pure game logic (no GTK): deterministic, unit-tested.
MarioGame    - the Gtk widget that draws it and handles the clicks / keys.

The look uses the colour palette of the reference image, but every sprite is an original drawing:
a small pixel runner, green tubes, bolted blocks, bushes, clouds and coins.
"""
from __future__ import annotations

import json
import logging
import math
import random
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from . import core

log = logging.getLogger("nothing_tasks")

# --------------------------------------------------------------------------- logic
W, H, GROUND = 108.0, 22.0, 4.0           # world units ("game pixels"); 1 unit = ch/22 screen px
FLOOR = H - GROUND                         # y of the ground surface
PX, PW, PH = 14.0, 6.0, 8.0                # player x, width, height
GRAV, V0 = 100.0, 40.0                     # jump: apex 8, airtime 0.8 s
T_APEX = V0 / GRAV


class RunnerWorld:
    def __init__(self, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.best = 0
        self.reset()

    def reset(self):
        self.speed, self.dist, self.coins, self.t = 34.0, 0.0, 0, 0.0
        self.py = self.vy = 0.0
        self.state = "run"                 # run | dead
        self.dead_t = 0.0
        self.obstacles: list[dict] = []
        self.items: list[dict] = []        # coins: x, h (height above ground centre), got
        self.spawn_in = 40.0
        self.clouds = [[self.rng.uniform(0, W), self.rng.uniform(2, 7), self.rng.uniform(8, 13)] for _ in range(3)]
        self.bushes = [self.rng.uniform(0, W) for _ in range(3)]
        self.events: list[str] = []

    @property
    def on_ground(self) -> bool:
        return self.py <= 0.0 and self.vy <= 0.0

    @property
    def score(self) -> int:
        return int(self.dist / 6) + 10 * self.coins

    def jump(self) -> bool:
        if self.state == "run" and self.on_ground:
            self.vy = V0
            self.events.append("jump")
            return True
        return False

    # -- one frame
    def step(self, dt: float, auto: bool = False) -> None:
        dt = min(max(dt, 0.0), 0.05)
        self.events = []
        if self.state == "dead":
            self.dead_t += dt
            return
        self.t += dt
        if auto:
            self._autopilot()
        if self.py > 0 or self.vy > 0:
            self.vy -= GRAV * dt
            self.py += self.vy * dt
            if self.py <= 0:
                self.py, self.vy = 0.0, 0.0
        self.speed = min(70.0, 34.0 + self.dist * 0.012)
        move = self.speed * dt
        self.dist += move
        for o in self.obstacles:
            o["x"] -= move
        for it in self.items:
            it["x"] -= move
        self.obstacles = [o for o in self.obstacles if o["x"] + o["w"] > -3]
        self.items = [i for i in self.items if i["x"] > -3 and not i["got"]]
        for c in self.clouds:
            c[0] -= move * 0.15
            if c[0] + c[2] < 0:
                c[:] = [W + self.rng.uniform(0, 20), self.rng.uniform(2, 7), self.rng.uniform(8, 13)]
        self.bushes = [(b - move * 0.6) if b > -6 else W + self.rng.uniform(0, 40) for b in self.bushes]
        self.spawn_in -= move
        if self.spawn_in <= 0:
            self._spawn()
        self._collide()

    def _spawn(self):
        kind = self.rng.choice(["tube", "tube", "block"])
        w, h = (5.0, self.rng.choice([4.0, 5.0])) if kind == "tube" else (4.0, 4.0)
        x = W + 2
        self.obstacles.append({"kind": kind, "x": x, "w": w, "h": h})
        if self.rng.random() < 0.6:        # a few coins above it, collectable at the top of the jump
            n = self.rng.choice([1, 2, 3])
            for i in range(n):
                self.items.append({"x": x + w / 2 - (n - 1) * 1.8 + i * 3.6, "h": 11.0, "got": False})
        self.spawn_in = self.rng.uniform(34 + self.speed * 0.55, 64 + self.speed * 0.55)

    def _autopilot(self):
        if not self.on_ground:
            return
        pc = PX + PW / 2
        for o in self.obstacles:
            d = (o["x"] + o["w"] / 2) - pc
            if d > 0:
                if d <= self.speed * T_APEX + 0.5:
                    self.jump()
                return

    def _collide(self):
        x0, x1, bottom, top = PX + 1, PX + PW - 1, self.py, self.py + PH - 1
        for o in self.obstacles:
            if x1 > o["x"] + 0.5 and x0 < o["x"] + o["w"] - 0.5 and bottom < o["h"] - 0.5:
                self.state, self.dead_t = "dead", 0.0
                self.best = max(self.best, self.score)
                self.events.append("dead")
                return
        for it in self.items:
            if not it["got"] and x1 > it["x"] - 1.6 and x0 < it["x"] + 1.6 \
                    and bottom < it["h"] + 1.6 and top > it["h"] - 1.6:
                it["got"] = True
                self.coins += 1
                self.events.append("coin")


# --------------------------------------------------------------------------- look
SPRITE = [".cccc.", "ccccss", ".ssess", ".ssss.", ".cccc.", "cccccc", ".bbbb."]
LEGS = {"a": ".k..k.", "b": "..kk..", "jump": "kk..kk", "dead": "k....k"}

MARIO = {
    "sky": "#A3D1C6", "cloud": "#FEFEFE", "ground": "#F7D2C9", "stripe_a": "#D19F46", "stripe_b": "#926C2D",
    "outline": "#020202", "tube": "#147C00", "tube_hi": "#58C844", "tube_dk": "#0B4A00",
    "block": "#F2D2C3", "block_edge": "#D19F46", "bolt": "#5BA39A", "bush": "#52C544", "bush_dk": "#2E8F2A",
    "c": "#D83018", "s": "#F2D2C3", "e": "#020202", "b": "#A83818", "k": "#3A1808",
    "coin": "#F4C430", "coin_dk": "#D19F46", "score": "#020202",
}


def pill_palette(pal: dict) -> dict:
    """Grey + accent version, built from the pill's own theme."""
    a, t, line, dim, surf, muted = pal["accent"], pal["text"], pal["line"], pal["dim"], pal["surface"], pal["muted"]
    return {
        "sky": None, "cloud": t, "ground": line, "stripe_a": dim, "stripe_b": line, "outline": line,
        "tube": line, "tube_hi": muted, "tube_dk": dim, "block": surf, "block_edge": muted, "bolt": muted,
        "bush": None, "bush_dk": None, "c": a, "s": t, "e": pal["bg"], "b": a, "k": muted,
        "coin": a, "coin_dk": a, "score": muted,
    }


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


DIGITS = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
}


def best_file():
    return core.STATE_DIR / "game.json"


def load_best() -> int:
    try:
        return int(json.loads(best_file().read_text()).get("best", 0))
    except (OSError, ValueError, TypeError):
        return 0


def save_best(n: int) -> None:
    try:
        core.atomic_write(best_file(), json.dumps({"best": int(n)}))
    except OSError as e:
        log.debug("cannot save best score: %s", e)


class MarioGame(Gtk.DrawingArea):
    """Attract mode: the runner plays itself. Click / Up / W takes over; after a few seconds
    without input it hands control back to the autopilot.

    Cheap by design: sprites and the scrolling ground are pre-rendered once and just blitted, colours
    are converted once, the timer only runs while the game is on screen, and it ticks slower while
    the autopilot is playing."""

    PLAYER_HOLD = 8.0           # seconds of manual control after the last input
    MS_AUTO, MS_MANUAL = 42, 33  # ~24 fps for the autopilot, 30 fps while you play

    def __init__(self, get_theme):
        super().__init__()
        self.get_theme = get_theme          # () -> (game_theme, pal, glass)
        self.world = RunnerWorld()
        self.world.best = load_best()
        self.k = 2.0
        self.player_until = 0.0
        self._timer = 0
        self._interval = 0
        self._last = 0.0
        self._cache_key = None
        self._P: dict = {}
        self._sprites: dict = {}
        self._ground = None
        self.sparks: list[list[float]] = []
        self.connect("draw", self._draw)

    def configure(self, cw: int, ch: int):
        self.set_size_request(cw, ch)
        self.k = ch / H
        self._cache_key = None              # rebuild the cached art at the new scale

    # -- control
    @property
    def manual(self) -> bool:
        return time.monotonic() < self.player_until

    def jump_input(self):
        self.player_until = time.monotonic() + self.PLAYER_HOLD
        if self.world.state == "dead":
            self.world.reset()
        self.world.jump()
        self._reschedule()
        self.queue_draw()

    def start(self):
        if not self._timer:
            self._last = time.monotonic()
            self._interval = self.MS_MANUAL if self.manual else self.MS_AUTO
            self._timer = GLib.timeout_add(self._interval, self._tick)

    def stop(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def _reschedule(self):
        want = self.MS_MANUAL if self.manual else self.MS_AUTO
        if self._timer and want != self._interval:
            GLib.source_remove(self._timer)
            self._interval = want
            self._timer = GLib.timeout_add(want, self._tick)

    def _on_screen(self) -> bool:
        top = self.get_toplevel().get_window() if self.get_toplevel() else None
        return bool(self.get_mapped() and top is not None and top.is_viewable()
                    and not (top.get_state() & Gdk.WindowState.ICONIFIED))

    def _tick(self):
        now = time.monotonic()
        dt, self._last = now - self._last, now
        if not self._on_screen():               # hidden by the window manager (Win+D...): don't burn CPU
            return True
        w = self.world
        w.step(dt, auto=not self.manual)
        for ev in w.events:
            if ev == "coin":
                self.sparks.append([PX + 3, FLOOR - 12, 0.0])
            elif ev == "dead":
                save_best(w.best)
        if self.sparks:
            self.sparks = [[x, y - 14 * dt, t + dt] for x, y, t in self.sparks if t < 0.4]
        if w.state == "dead" and w.dead_t > (3.0 if self.manual else 1.0):
            w.reset()
            self.player_until = 0.0
        self.queue_draw()
        want = self.MS_MANUAL if self.manual else self.MS_AUTO
        if want != self._interval:          # switch frame rate (manual <-> autopilot)
            self._interval = want
            self._timer = GLib.timeout_add(want, self._tick)
            return False
        return True

    def reset_best(self):
        self.world.best = 0
        save_best(0)

    # -- cached art
    def _prepare(self, theme, pal):
        key = (theme, self.k, tuple(sorted((a, b) for a, b in pal.items() if isinstance(b, str))))
        if key == self._cache_key:
            return
        self._cache_key = key
        src = MARIO if theme == "mario" else pill_palette(pal)
        self._P = {n: (_rgb(c) if c else None) for n, c in src.items()}
        self._sprites = {}
        self._ground = None

    def _sprite(self, legs_key):
        surf = self._sprites.get(legs_key)
        if surf is None:
            k, P = self.k, self._P
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(PW * k) + 2, int(PH * k) + 2)
            c = cairo.Context(surf)
            for r, row in enumerate(SPRITE + [LEGS[legs_key]]):
                for i, ch in enumerate(row):
                    if ch != ".":
                        c.set_source_rgb(*P[ch])
                        c.rectangle(round(i * k), round(r * k), math.ceil(k), math.ceil(k))
                        c.fill()
            self._sprites[legs_key] = surf
        return surf

    def _ground_surface(self):
        if self._ground is None:
            k, P = self.k, self._P
            gw = int((W + 4) * k)
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, gw, int(GROUND * k) + 1)
            c = cairo.Context(surf)
            c.set_source_rgb(*P["ground"])
            c.rectangle(0, 0, gw, round(k))
            c.fill()
            for i in range(int(W / 2) + 4):                       # 1-unit stripes, period 2 units
                for off, col in ((0, "stripe_a"), (1, "stripe_b")):
                    c.set_source_rgb(*P[col])
                    c.rectangle(round((i * 2 + off) * k), round(k), math.ceil(k), round((GROUND - 1) * k) + 1)
                    c.fill()
            c.set_source_rgb(*P["outline"])
            c.rectangle(0, 0, gw, max(1, round(k / 2)))
            c.fill()
            self._ground = surf
        return self._ground

    # -- drawing
    def _draw(self, _w, cr):
        theme, pal, glass = self.get_theme()
        self._prepare(theme, pal)
        P, k, w = self._P, self.k, self.world
        width = self.get_allocated_width()
        mario = theme == "mario"

        def rect(x, y, ww, hh, col, a=1.0):
            if col is None:
                return
            cr.set_source_rgba(col[0], col[1], col[2], a)
            x0, y0 = round(x * k), round(y * k)
            cr.rectangle(x0, y0, max(1, round((x + ww) * k) - x0), max(1, round((y + hh) * k) - y0))
            cr.fill()

        if P["sky"]:
            rect(0, 0, W, H, P["sky"], 0.9 if glass else 1.0)
        ca = 0.9 if mario else 0.12
        for cx, cy, cw_ in w.clouds:                               # clouds (parallax)
            rect(cx + 1, cy, cw_ - 2, 2.5, P["cloud"], ca)
            rect(cx, cy + 1, cw_, 1.5, P["cloud"], ca)
            rect(cx + cw_ * 0.3, cy - 1, cw_ * 0.35, 1.5, P["cloud"], ca)
        if P["bush"]:
            for bx in w.bushes:                                    # bushes (parallax)
                for i in range(3):
                    rect(bx + i * 2.2, FLOOR - 2.5 + (0.6 if i == 1 else 0), 2.6, 2.5, P["bush"])
                    rect(bx + i * 2.2 + 0.5, FLOOR - 1.5, 1.2, 0.7, P["bush_dk"])
        cr.set_source_surface(self._ground_surface(), round((-2 - (w.dist % 2)) * k), round(FLOOR * k))
        cr.paint()                                                 # ground: one blit

        for o in w.obstacles:
            top = FLOOR - o["h"]
            if o["kind"] == "tube":
                rect(o["x"], top + 1.5, o["w"], o["h"] - 1.5, P["tube"])
                rect(o["x"] + 0.7, top + 1.5, 1.0, o["h"] - 1.5, P["tube_hi"])
                rect(o["x"] + o["w"] - 1.2, top + 1.5, 1.2, o["h"] - 1.5, P["tube_dk"])
                rect(o["x"] - 0.5, top, o["w"] + 1, 1.7, P["tube"])
                rect(o["x"] + 0.2, top + 0.2, 1.0, 1.3, P["tube_hi"])
                rect(o["x"] - 0.5, top + 1.5, o["w"] + 1, 0.3, P["outline"])
            else:
                rect(o["x"], top, o["w"], o["h"], P["block_edge"])
                rect(o["x"] + 0.4, top + 0.4, o["w"] - 0.8, o["h"] - 0.8, P["block"])
                for dx, dy in ((0.8, 0.8), (o["w"] - 1.6, 0.8), (0.8, o["h"] - 1.6), (o["w"] - 1.6, o["h"] - 1.6)):
                    rect(o["x"] + dx, top + dy, 0.8, 0.8, P["bolt"])

        for it in w.items:                                         # coins: spinning
            cw_ = 0.8 + 2.2 * abs(math.cos(w.t * 8 + it["x"] * 0.3))
            rect(it["x"] - cw_ / 2, FLOOR - it["h"] - 1.6, cw_, 3.2, P["coin"])
            rect(it["x"] - cw_ / 2 + 0.3, FLOOR - it["h"] - 1.2, max(0.4, cw_ * 0.3), 2.4, P["coin_dk"])
        for sx, sy, t in self.sparks:
            rect(sx, sy, 1.0, 1.0, P["coin"], 1 - t / 0.4)

        # player: pre-rendered frames, one blit
        legs = "dead" if w.state == "dead" else "jump" if not w.on_ground else ("a" if int(w.t * 10) % 2 == 0 else "b")
        if not (w.state == "dead" and int(w.dead_t * 8) % 2 == 0):
            cr.set_source_surface(self._sprite(legs), round(PX * k), round((FLOOR - w.py - PH) * k))
            cr.paint()

        # score (top-right, tiny dot font): one path, one fill
        txt = str(w.score)
        px = max(1, round(k / 2))
        cx0 = width - 17 * k / 2 - len(txt) * 4 * px
        cr.set_source_rgba(*P["score"], 0.85)
        for n, chx in enumerate(txt):
            for ry, line in enumerate(DIGITS[chx]):
                for rx, bit in enumerate(line):
                    if bit == "1":
                        cr.rectangle(cx0 + (n * 4 + rx) * px, 3 * k / 2 + ry * px, px, px)
        cr.fill()
