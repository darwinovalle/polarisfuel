import pytest
from decimal import Decimal

from django.apps import apps
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction



def get_model(name):
    model = apps.get_model("stations", name)
    assert model is not None, f"Model stations.{name} must exist"
    return model


@pytest.mark.django_db
def test_required_models_exist():
    for name in ["Truckstop", "Rack", "CurrentPrice", "ImportJob", "ImportIssue"]:
        assert apps.get_model("stations", name) is not None


@pytest.mark.django_db
def test_truckstop_has_identity_fields():
    Truckstop = get_model("Truckstop")
    field_names = {f.name for f in Truckstop._meta.get_fields()}

    expected = {
        "opis_truckstop_id",
        "name",
        "address",
        "city",
        "state",
    }
    assert expected.issubset(field_names)


@pytest.mark.django_db
def test_rack_has_fk_to_truckstop_and_rack_id():
    Rack = get_model("Rack")
    field_names = {f.name for f in Rack._meta.get_fields()}

    assert "truckstop" in field_names
    assert "rack_id" in field_names


@pytest.mark.django_db
def test_rack_is_unique_per_truckstop():
    Truckstop = get_model("Truckstop")
    Rack = get_model("Rack")

    ts = Truckstop.objects.create(
        opis_truckstop_id="1001",
        name="Pilot Test",
        address="123 Main St",
        city="Dallas",
        state="TX",
    )
    Rack.objects.create(truckstop=ts, rack_id=101)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Rack.objects.create(truckstop=ts, rack_id=101)


@pytest.mark.django_db
def test_current_price_belongs_to_rack():
    Truckstop = get_model("Truckstop")
    Rack = get_model("Rack")
    CurrentPrice = get_model("CurrentPrice")

    ts = Truckstop.objects.create(
        opis_truckstop_id="1002",
        name="Love's Test",
        address="456 Oak St",
        city="Houston",
        state="TX",
    )
    rack = Rack.objects.create(truckstop=ts, rack_id=102)

    price = CurrentPrice.objects.create(
        rack=rack,
        retail_price=Decimal("3.599"),
    )

    assert price.rack_id == rack.id


@pytest.mark.django_db
def test_current_price_must_be_positive():
    Truckstop = get_model("Truckstop")
    Rack = get_model("Rack")
    CurrentPrice = get_model("CurrentPrice")

    ts = Truckstop.objects.create(
        opis_truckstop_id="1003",
        name="TA Test",
        address="789 Pine St",
        city="Austin",
        state="TX",
    )
    rack = Rack.objects.create(truckstop=ts, rack_id=103)

    price = CurrentPrice(
        rack=rack,
        retail_price=Decimal("-1.00"),
    )

    with pytest.raises(ValidationError):
        price.full_clean()


@pytest.mark.django_db
def test_import_issue_links_to_import_job():
    ImportJob = get_model("ImportJob")
    ImportIssue = get_model("ImportIssue")

    job = ImportJob.objects.create(
        source_filename="prices_sample.xlsx",
        status="failed",
        rows_total=10,
        rows_inserted=7,
        rows_deduped=2,
        rows_failed=1,
    )

    issue = ImportIssue.objects.create(
        import_job=job,
        row_number=4,
        issue_type="validation_error",
        message="Retail Price missing",
        raw_payload={"row": 4},
    )

    assert issue.import_job_id == job.id
