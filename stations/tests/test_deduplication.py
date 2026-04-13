from decimal import Decimal

from stations.services.deduplication import collapse_duplicates_keep_highest


def test_no_duplicates_returns_same_rows():
    rows = [
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.500"),
        },
        {
            "OPIS Truckstop ID": 1002,
            "Truckstop Name": "TA",
            "Address": "456 OAK",
            "City": "HOUSTON",
            "State": "TX",
            "Rack ID": 102,
            "Retail Price": Decimal("3.700"),
        },
    ]

    result = collapse_duplicates_keep_highest(rows)

    assert len(result["rows"]) == 2
    assert result["duplicates_removed"] == 0


def test_duplicates_keep_highest_price():
    rows = [
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.500"),
        },
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.900"),
        },
    ]

    result = collapse_duplicates_keep_highest(rows)

    assert len(result["rows"]) == 1
    assert result["duplicates_removed"] == 1
    assert result["rows"][0]["Retail Price"] == Decimal("3.900")


def test_deterministic_when_same_price_keeps_first_seen():
    rows = [
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT A",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.700"),
        },
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT B",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.700"),
        },
    ]

    result = collapse_duplicates_keep_highest(rows)

    assert len(result["rows"]) == 1
    assert result["rows"][0]["Truckstop Name"] == "PILOT A"
    assert result["duplicates_removed"] == 1


def test_duplicate_key_uses_all_identity_fields():
    rows = [
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 101,
            "Retail Price": Decimal("3.700"),
        },
        {
            "OPIS Truckstop ID": 1001,
            "Truckstop Name": "PILOT",
            "Address": "123 MAIN",
            "City": "DALLAS",
            "State": "TX",
            "Rack ID": 999,  # different rack
            "Retail Price": Decimal("3.900"),
        },
    ]

    result = collapse_duplicates_keep_highest(rows)

    assert len(result["rows"]) == 2
    assert result["duplicates_removed"] == 0