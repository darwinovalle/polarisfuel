from decimal import Decimal

import pytest

from stations.models import CurrentPrice, ImportIssue, ImportJob, Rack, Truckstop
from stations.services.import_pipeline import run_import


@pytest.mark.django_db
def test_run_import_creates_job_and_persists_valid_rows():
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        },
        {
            "OPIS Truckstop ID": "1002",
            "Truckstop Name": "TA",
            "Address": "456 OAK",
            "City": "HOUSTON",
            "State": "TX",
            "Rack ID": "102",
            "Retail Price": "3.700",
        },
    ]

    result = run_import(rows, source_filename="sample.xlsx")

    assert result["job_id"] is not None
    assert result["rows_total"] == 2
    assert result["rows_inserted"] == 2
    assert result["rows_failed"] == 0
    assert result["rows_deduped"] == 0

    assert Truckstop.objects.count() == 2
    assert Rack.objects.count() == 2
    assert CurrentPrice.objects.count() == 2


@pytest.mark.django_db
def test_run_import_records_issues_for_invalid_rows():
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        },
        {
            "OPIS Truckstop ID": "1002",
            "Truckstop Name": "TA",
            "Address": "456 OAK",
            "City": "HOUSTON",
            "State": "TX",
            "Rack ID": "102",
            "Retail Price": "abc",
        },
    ]

    result = run_import(rows, source_filename="sample.xlsx")

    assert result["rows_total"] == 2
    assert result["rows_inserted"] == 1
    assert result["rows_failed"] == 1

    job = ImportJob.objects.get(id=result["job_id"])
    assert ImportIssue.objects.filter(import_job=job).count() == 1


@pytest.mark.django_db
def test_run_import_applies_dedupe_and_tracks_removed_count():
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.500",
        },
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.900",
        },
    ]

    result = run_import(rows, source_filename="sample.xlsx")

    assert result["rows_total"] == 2
    assert result["rows_deduped"] == 1
    assert result["rows_inserted"] == 1
    assert CurrentPrice.objects.count() == 1
    assert CurrentPrice.objects.first().retail_price == Decimal("3.900")


@pytest.mark.django_db
def test_run_import_rolls_back_on_persistence_error(monkeypatch):
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        }
    ]

    original_create = CurrentPrice.objects.create

    def boom(*args, **kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(CurrentPrice.objects, "create", boom)

    with pytest.raises(RuntimeError):
        run_import(rows, source_filename="sample.xlsx")

    assert Truckstop.objects.count() == 0
    assert Rack.objects.count() == 0
    assert CurrentPrice.objects.count() == 0
