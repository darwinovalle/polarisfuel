from decimal import Decimal

import pytest

from stations.services.parsing import (
    REQUIRED_HEADERS,
    normalize_row,
    parse_price,
    validate_headers,
    parse_rows,
)


def test_required_headers_constant_matches_contract():
    assert REQUIRED_HEADERS == [
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
        "Retail Price",
    ]


def test_required_headers_present_accepts_exact_contract():
    headers = [
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
        "Retail Price",
    ]
    validate_headers(headers)


def test_validate_headers_ignores_column_order():
    headers = [
        "Rack ID",
        "Retail Price",
        "City",
        "Address",
        "State",
        "Truckstop Name",
        "OPIS Truckstop ID",
    ]
    validate_headers(headers)


def test_missing_header_returns_clear_error():
    headers = [
        "OPIS Truckstop ID",
        "Truckstop Name",
        "Address",
        "City",
        "State",
        "Rack ID",
    ]
    with pytest.raises(ValueError) as exc:
        validate_headers(headers)

    assert "Retail Price" in str(exc.value)


def test_normalize_row_trims_and_uppercases_text_fields():
    row = {
        "OPIS Truckstop ID": "1001",
        "Truckstop Name": "  pilot travel center  ",
        "Address": " 123 Main St ",
        "City": "  dallas ",
        "State": " tx ",
        "Rack ID": "101",
        "Retail Price": "3.599",
    }

    normalized = normalize_row(row)

    assert normalized["Truckstop Name"] == "PILOT TRAVEL CENTER"
    assert normalized["Address"] == "123 MAIN ST"
    assert normalized["City"] == "DALLAS"
    assert normalized["State"] == "TX"


def test_normalize_row_keeps_required_keys():
    row = {
        "OPIS Truckstop ID": "1001",
        "Truckstop Name": "Pilot",
        "Address": "123 Main",
        "City": "Dallas",
        "State": "TX",
        "Rack ID": "101",
        "Retail Price": "3.599",
    }

    normalized = normalize_row(row)

    for key in REQUIRED_HEADERS:
        assert key in normalized


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("3.599", Decimal("3.599")),
        (" 3.599 ", Decimal("3.599")),
        ("$3.599", Decimal("3.599")),
        ("0.001", Decimal("0.001")),
    ],
)
def test_parse_price_accepts_valid_formats(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "", None, "3,59", "12..1"])
def test_parse_price_rejects_non_numeric(raw):
    with pytest.raises(ValueError):
        parse_price(raw)


@pytest.mark.parametrize("raw", ["-1.00", "-0.01", "0", "0.000"])
def test_parse_price_rejects_non_positive(raw):
    with pytest.raises(ValueError):
        parse_price(raw)


def test_parse_rows_mixed_valid_and_invalid():
    rows = [
        # valid
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "Pilot",
            "Address": "123 Main",
            "City": "Dallas",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        },
        # invalid price
        {
            "OPIS Truckstop ID": "1002",
            "Truckstop Name": "TA",
            "Address": "456 Oak",
            "City": "Houston",
            "State": "TX",
            "Rack ID": "102",
            "Retail Price": "abc",
        },
        # missing value
        {
            "OPIS Truckstop ID": "1003",
            "Truckstop Name": "Love's",
            "Address": "789 Pine",
            "City": "Austin",
            "State": "TX",
            "Rack ID": "103",
            "Retail Price": "",
        },
    ]

    result = parse_rows(rows)

    assert len(result["valid_rows"]) == 1
    assert len(result["errors"]) == 2

    # Check structure
    error = result["errors"][0]
    assert "row" in error
    assert "message" in error


    result = parse_rows(rows)

    assert len(result["valid_rows"]) == 1
    assert len(result["errors"]) == 2

    # Check error structure
    error = result["errors"][0]
    assert "row" in error
    assert "message" in error


def test_parse_rows_all_valid():
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "Pilot",
            "Address": "123 Main",
            "City": "Dallas",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        },
        {
            "OPIS Truckstop ID": "1002",
            "Truckstop Name": "TA",
            "Address": "456 Oak",
            "City": "Houston",
            "State": "TX",
            "Rack ID": "102",
            "Retail Price": "3.700",
        },
    ]

    result = parse_rows(rows)

    assert len(result["valid_rows"]) == 2
    assert result["errors"] == []


def test_parse_rows_converts_types_correctly():
    rows = [
        {
            "OPIS Truckstop ID": "1001",
            "Truckstop Name": "Pilot",
            "Address": "123 Main",
            "City": "Dallas",
            "State": "TX",
            "Rack ID": "101",
            "Retail Price": "3.599",
        }
    ]

    result = parse_rows(rows)
    row = result["valid_rows"][0]

    assert isinstance(row["OPIS Truckstop ID"], int)
    assert isinstance(row["Rack ID"], int)
    assert isinstance(row["Retail Price"], Decimal)
