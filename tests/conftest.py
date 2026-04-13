import pytest


@pytest.fixture
def sample_excel_row():
    return {
        "OPIS Truckstop ID": "TS-1001",
        "Truckstop Name": "Pilot Test",
        "Address": "123 Main St",
        "City": "Dallas",
        "State": "TX",
        "Rack ID": "R-01",
        "Retail Price": "3.599",
    }


@pytest.fixture
def sample_excel_rows(sample_excel_row):
    return [sample_excel_row]


@pytest.fixture
def user_payload():
    return {
        "username": "tester",
        "email": "tester@example.com",
        "password": "StrongPass123!",
    }