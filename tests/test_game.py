import random

import pytest

pytest.importorskip("gi")
from nothing_tasks import core, game, theme
from nothing_tasks.game import MARIO, RunnerWorld, pill_palette


def run(world, seconds, auto=True, fps=30):
    for _ in range(int(seconds * fps)):
        world.step(1 / fps, auto=auto)


@pytest.mark.parametrize("seed", range(8))
def test_autopilot_plays_forever(seed):
    w = RunnerWorld(random.Random(seed))
    run(w, 90)
    assert w.state == "run" and w.score > 100 and w.speed <= 70


def test_without_input_the_runner_hits_something():
    w = RunnerWorld(random.Random(1))
    run(w, 30, auto=False)
    assert w.state == "dead" and "dead" not in w.events        # events are per frame


def test_jump_rules_and_physics():
    w = RunnerWorld(random.Random(0))
    assert w.jump() and not w.jump()                              # no double jump in the air
    peak = 0.0
    for _ in range(60):
        w.step(1 / 60)
        peak = max(peak, w.py)
    assert 7.0 < peak <= 8.2 and w.on_ground                      # apex ~8, lands again


def test_coins_score_and_speed_ramp():
    w = RunnerWorld(random.Random(2))
    assert w.speed == 34.0 and w.score == 0
    w.items.append({"x": game.PX + 3, "h": 1.5, "got": False})   # coin right at the runner
    w.step(1 / 30)
    assert w.coins == 1 and w.score >= 10 and "coin" in w.events
    run(w, 60)
    assert w.speed > 40 and w.dist > 100


def test_dead_world_stands_still_until_reset():
    w = RunnerWorld(random.Random(3))
    run(w, 30, auto=False)
    d = w.dist
    w.step(1 / 30)
    assert w.dist == d
    w.reset()
    assert w.state == "run" and w.score == 0 and w.coins == 0


def test_palettes_cover_everything_the_drawing_uses():
    assert set(MARIO) == set(pill_palette({**theme.PALETTES["dark"], "accent": "#D71921"}))
    assert MARIO["sky"] == "#A3D1C6" and MARIO["tube"] == "#147C00"      # from the reference image


def test_best_score_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "STATE_DIR", tmp_path)
    assert game.load_best() == 0
    game.save_best(321)
    assert game.load_best() == 321


def test_theme_resolve():
    assert theme.resolve("dark") == "dark" and theme.resolve("light") == "light"
    assert theme.resolve("auto") in ("dark", "light")
    assert set(theme.PALETTES["dark"]) == set(theme.PALETTES["light"])
