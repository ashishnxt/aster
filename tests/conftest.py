import json

import pytest

from nothing_tasks import core


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolated config/state/vault directories."""
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(core, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(core, "CONFIG_FILE", tmp_path / "cfg" / "config.json")
    monkeypatch.setattr(core, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(core, "TIMER_FILE", tmp_path / "state" / "timer.json")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.json").write_text(json.dumps({"vault": str(vault)}))
    return tmp_path
