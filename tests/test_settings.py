"""Saved paper size. These tests do not touch any printer's settings."""
import pytest

from l6460 import config, settings
from l6460.config import PAPERS


@pytest.fixture(autouse=True)
def private_settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")


def test_default_is_a4_when_nothing_saved():
    assert settings.load_paper().name == "A4"


def test_saved_size_is_used():
    settings.save_paper(PAPERS["Letter"])
    assert settings.load_paper().name == "Letter"


@pytest.mark.parametrize("content", ["not json", '{"paper": "Legal"}', "[]", ""])
def test_unreadable_or_unsupported_setting_falls_back_to_a4(content):
    config.SETTINGS_FILE.write_text(content, encoding="utf-8")
    assert settings.load_paper().name == "A4"


def test_only_sizes_the_driver_allows_for_2_sided():
    assert set(PAPERS) == {"A4", "Letter", "B5", "16K"}


def test_guard_stops_only_2_sided_jobs_of_another_size():
    from types import SimpleNamespace
    from l6460.service import wrong_size_for_duplex
    a4 = PAPERS["A4"]
    job = lambda paper_id, duplex: SimpleNamespace(PaperSize=paper_id, Duplex=duplex)
    assert wrong_size_for_duplex(job(1, 2), a4)        # Letter, 2-sided: stop
    assert wrong_size_for_duplex(job(256, 3), a4)      # custom size, 2-sided: stop
    assert not wrong_size_for_duplex(job(9, 2), a4)    # A4, 2-sided: fine
    assert not wrong_size_for_duplex(job(1, 1), a4)    # Letter, one-sided: not this guard's job
    assert not wrong_size_for_duplex(None, a4)         # no settings yet
