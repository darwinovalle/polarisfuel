import pytest
import httpx

from stations.services.provider_errors import (
    ProviderBadResponseError,
    ProviderTimeoutError,
)
from stations.services.providers_nominatim import NominatimGeocodingProvider
from stations.services.providers_osrm import OsrmDirectionsProvider
from stations.services.providers_tomtom import TomTomDirectionsProvider


class DummyResponse:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


def test_nominatim_geocode_success(monkeypatch):
    provider = NominatimGeocodingProvider(timeout=2.0, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(
            status_code=200,
            json_data=[
                {
                    "lat": "32.7767",
                    "lon": "-96.7970",
                    "display_name": "Dallas, Texas, USA",
                }
            ],
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    result = provider.geocode("Dallas, TX")

    assert result["lat"] == 32.7767
    assert result["lon"] == -96.797
    assert "Dallas" in result["display_name"]


def test_nominatim_geocode_timeout(monkeypatch):
    provider = NominatimGeocodingProvider(timeout=0.01, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ProviderTimeoutError):
        provider.geocode("Dallas, TX")


def test_nominatim_geocode_bad_response(monkeypatch):
    provider = NominatimGeocodingProvider(timeout=2.0, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(status_code=500, json_data={"error": "server error"})

    monkeypatch.setattr(httpx, "get", fake_get)

    with pytest.raises(ProviderBadResponseError):
        provider.geocode("Dallas, TX")


def test_osrm_route_success(monkeypatch):
    provider = OsrmDirectionsProvider(timeout=2.0, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(
            status_code=200,
            json_data={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 120000.0,
                        "duration": 5400.0,
                        "geometry": "abc123",
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}
    result = provider.route(origin, destination)

    assert result["distance_m"] == 120000.0
    assert result["duration_s"] == 5400.0
    assert result["geometry"] == "abc123"


def test_osrm_route_timeout(monkeypatch):
    provider = OsrmDirectionsProvider(timeout=0.01, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}

    with pytest.raises(ProviderTimeoutError):
        provider.route(origin, destination)


def test_osrm_route_bad_payload(monkeypatch):
    provider = OsrmDirectionsProvider(timeout=2.0, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(status_code=200, json_data={"code": "NoRoute", "routes": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}

    with pytest.raises(ProviderBadResponseError):
        provider.route(origin, destination)


def test_osrm_route_includes_alternatives_when_requested(monkeypatch):
    provider = OsrmDirectionsProvider(timeout=2.0, max_retries=1)
    observed = {"params": {}}

    def fake_get(url, params=None, timeout=None):
        observed["params"] = params or {}
        return DummyResponse(
            status_code=200,
            json_data={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 100000.0,
                        "duration": 5000.0,
                        "geometry": {
                            "coordinates": [[-96.79, 32.77], [-95.36, 29.76]],
                        },
                    },
                    {
                        "distance": 105000.0,
                        "duration": 5200.0,
                        "geometry": {
                            "coordinates": [[-96.79, 32.77], [-95.9, 30.4], [-95.36, 29.76]],
                        },
                    },
                ],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}
    result = provider.route(origin, destination, include_alternatives=True)

    assert observed["params"]["alternatives"] == "true"
    assert len(result["alternatives"]) == 2



def test_tomtom_route_success(monkeypatch):
    provider = TomTomDirectionsProvider(api_key="test-key", timeout=2.0, max_retries=1)
    observed = {"url": ""}

    def fake_get(url, params=None, timeout=None):
        observed["url"] = url
        return DummyResponse(
            status_code=200,
            json_data={
                "routes": [
                    {
                        "summary": {
                            "lengthInMeters": 145000.0,
                            "travelTimeInSeconds": 6300.0,
                        },
                        "legs": [
                            {
                                "points": [
                                    {"latitude": 32.7767, "longitude": -96.7970},
                                    {"latitude": 31.9686, "longitude": -99.9018},
                                ]
                            },
                            {
                                "points": [
                                    {"latitude": 31.9686, "longitude": -99.9018},
                                    {"latitude": 29.7604, "longitude": -95.3698},
                                ]
                            },
                        ],
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}
    result = provider.route(origin, destination)

    assert "calculateRoute/32.7767,-96.797:29.7604,-95.3698/json" in observed["url"]
    assert result["distance_m"] == 145000.0
    assert result["duration_s"] == 6300.0
    assert result["geometry"] == [
        [32.7767, -96.7970],
        [31.9686, -99.9018],
        [29.7604, -95.3698],
    ]


def test_tomtom_route_timeout(monkeypatch):
    provider = TomTomDirectionsProvider(api_key="test-key", timeout=0.01, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}

    with pytest.raises(ProviderTimeoutError):
        provider.route(origin, destination)


def test_tomtom_route_bad_payload(monkeypatch):
    provider = TomTomDirectionsProvider(api_key="test-key", timeout=2.0, max_retries=1)

    def fake_get(url, params=None, timeout=None):
        return DummyResponse(status_code=200, json_data={"routes": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}

    with pytest.raises(ProviderBadResponseError):
        provider.route(origin, destination)


def test_tomtom_route_includes_alternatives_when_requested(monkeypatch):
    provider = TomTomDirectionsProvider(api_key="test-key", timeout=2.0, max_retries=1)
    observed = {"params": {}}

    def fake_get(url, params=None, timeout=None):
        observed["params"] = params or {}
        return DummyResponse(
            status_code=200,
            json_data={
                "routes": [
                    {
                        "summary": {
                            "lengthInMeters": 145000.0,
                            "travelTimeInSeconds": 6300.0,
                        },
                        "legs": [
                            {
                                "points": [
                                    {"latitude": 32.7767, "longitude": -96.7970},
                                    {"latitude": 29.7604, "longitude": -95.3698},
                                ]
                            }
                        ],
                    },
                    {
                        "summary": {
                            "lengthInMeters": 150000.0,
                            "travelTimeInSeconds": 6400.0,
                        },
                        "legs": [
                            {
                                "points": [
                                    {"latitude": 32.7767, "longitude": -96.7970},
                                    {"latitude": 31.2, "longitude": -96.0},
                                    {"latitude": 29.7604, "longitude": -95.3698},
                                ]
                            }
                        ],
                    },
                ]
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)

    origin = {"lat": 32.7767, "lon": -96.7970}
    destination = {"lat": 29.7604, "lon": -95.3698}
    result = provider.route(origin, destination, include_alternatives=True)

    assert observed["params"]["maxAlternatives"] == "2"
    assert len(result["alternatives"]) == 2
