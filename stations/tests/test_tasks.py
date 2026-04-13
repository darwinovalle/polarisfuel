import pytest
from pathlib import Path

from stations.tasks import run_daily_import

@pytest.mark.django_db
def test_run_daily_import_skips_when_env_missing(monkeypatch):
    monkeypatch.delenv("EXCEL_SOURCE_PATH", raising=False)
    result = run_daily_import()
    assert result["status"] == "skipped"

@pytest.mark.django_db
def test_run_daily_import_skips_when_file_missing(monkeypatch):
    monkeypatch.setenv("EXCEL_SOURCE_PATH", "/tmp/does_not_exist.xlsx")
    result = run_daily_import()
    assert result["status"] == "skipped"