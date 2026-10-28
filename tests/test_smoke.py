"""Smoke tests: the package imports and config resolves project paths."""

from datetime import date

import tpt
from tpt import config


def test_package_imports():
    assert tpt.__version__


def test_paths_are_inside_project_root():
    root = config.PROJECT_ROOT
    assert (root / "pyproject.toml").exists()
    for path in (
        config.DATA_DIR,
        config.RAW_DIR,
        config.INTERIM_DIR,
        config.PROCESSED_DIR,
        config.REFERENCE_DIR,
        config.PUBLISHED_DIR,
    ):
        assert path.is_relative_to(root)


def test_sample_window_starts_jan_2017():
    assert config.SAMPLE_START == date(2017, 1, 1)
    assert config.SAMPLE_END is None or config.SAMPLE_END > config.SAMPLE_START


def test_keys_are_optional(monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    monkeypatch.delenv("BLS_API_KEY", raising=False)
    assert config.census_api_key() is None
    assert config.bls_api_key() is None


def test_keys_read_from_env(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "abc")
    monkeypatch.setenv("BLS_API_KEY", "  xyz  ")
    assert config.census_api_key() == "abc"
    assert config.bls_api_key() == "xyz"


def test_blank_key_treated_as_missing(monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "")
    assert config.census_api_key() is None
