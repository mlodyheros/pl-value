import os
import time

import pandas as pd

from backend import refresh


def _setup(tmp_path, monkeypatch, gameweeks=4, page_age_days=1):
    dataset = tmp_path / "players.csv"
    pd.DataFrame({"name": ["A"], "fpl_gameweeks": [gameweeks]}).to_csv(dataset, index=False)
    pages = tmp_path / "tm"
    pages.mkdir()
    page = pages / "squad_11.html"
    page.write_text("<html></html>")
    old = time.time() - page_age_days * 24 * 3600
    os.utime(page, (old, old))
    monkeypatch.setattr(refresh, "PROCESSED_DATASET_PATH", dataset)
    monkeypatch.setattr(refresh, "TRANSFERMARKT_RAW_DIR", pages)


def test_nothing_to_do_when_the_data_is_current(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert refresh.reasons_to_refresh(finished_gameweeks=4) == []


def test_a_finished_gameweek_triggers_a_refresh(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert any("gameweek 5" in reason for reason in refresh.reasons_to_refresh(finished_gameweeks=5))


def test_week_old_squad_pages_trigger_a_refresh(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, page_age_days=8)
    assert any("Transfermarkt" in reason for reason in refresh.reasons_to_refresh(finished_gameweeks=4))


def test_no_dataset_is_a_reason_on_its_own(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "PROCESSED_DATASET_PATH", tmp_path / "missing.csv")
    assert refresh.reasons_to_refresh(finished_gameweeks=1) == ["there is no dataset yet"]


def test_a_quiet_day_does_not_rebuild(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(refresh.fpl_client, "get_bootstrap_static",
                        lambda refresh=False: {"events": [{"finished": True}] * 4})

    assert refresh.refresh() is False
