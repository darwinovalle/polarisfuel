import pytest
from django.urls import reverse

from stations import views
from stations.models import CurrentPrice, Rack, Truckstop
from stations.services.provider_errors import ProviderTimeoutError


@pytest.fixture(autouse=True)
def disable_station_geocoding_attempts(monkeypatch):
    # Keep unit tests deterministic and fast unless a test explicitly enables station geocoding.
    monkeypatch.setattr(views, "MAX_STATION_GEOCODE_ATTEMPTS", 0)
    monkeypatch.setattr(views, "build_direct_route_alternatives", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        views,
        "build_osrm_geometry_path",
        lambda origin_coords, destination_coords, waypoints: views.build_path_with_waypoints(
            origin_coords,
            destination_coords,
            waypoints,
        ),
    )


def create_station_price(
    retail_price: float = 3.000,
    opis_truckstop_id: int = 1001,
    rack_id: int = 1,
    name: str = "Test Fuel",
    city: str = "Amarillo",
    state: str = "TX",
):
    truckstop = Truckstop.objects.create(
        opis_truckstop_id=opis_truckstop_id,
        name=name,
        address="123 Main St",
        city=city,
        state=state,
    )
    rack = Rack.objects.create(truckstop=truckstop, rack_id=rack_id)
    CurrentPrice.objects.create(rack=rack, retail_price=retail_price)


def optimize_query(**overrides):
    query = {
        "origin": "Oklahoma City, Oklahoma, United States",
        "destination": "Denver, Colorado, United States",
        "origin_lat": "35.4676",
        "origin_lon": "-97.5164",
        "destination_lat": "39.7392",
        "destination_lon": "-104.9903",
        "time_weight": "0.6",
        "price_weight": "0.4",
    }
    query.update(overrides)
    return query


@pytest.mark.django_db
def test_optimize_route_applies_custom_vehicle_profile(client, monkeypatch):
    create_station_price(retail_price=3.150)

    def fake_optimize(
        self,
        origin_query,
        destination_query,
        candidate_stations,
        weights,
        origin_coords,
        destination_coords,
    ):
        station = candidate_stations[0]
        alternative = {
            "station": station,
            "distance_m": 160934.4,
            "duration_s": 7200.0,
            "geometry": "",
            "estimated_fuel_cost": 15.75,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
        }
        return {
            "origin": {
                "lat": float(origin_coords["lat"]),
                "lon": float(origin_coords["lon"]),
                "display_name": origin_query,
            },
            "destination": {
                "lat": float(destination_coords["lat"]),
                "lon": float(destination_coords["lon"]),
                "display_name": destination_query,
            },
            "best_option": alternative,
            "alternatives": [alternative],
            "weights": weights,
        }

    monkeypatch.setattr(views.RouteOptimizer, "optimize", fake_optimize)

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(avg_mpg="20", tank_capacity_gal="10"),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["assumptions"]["avg_mpg"] == pytest.approx(20.0)
    assert payload["assumptions"]["tank_capacity_gal"] == pytest.approx(10.0)
    assert payload["fuel_plan"]["gallons_needed"] == pytest.approx(5.0)
    assert payload["fuel_plan"]["max_range_mi"] == pytest.approx(200.0)
    assert payload["fuel_plan"]["min_refuel_stops"] == 0


@pytest.mark.django_db
def test_optimize_route_rejects_invalid_vehicle_profile(client):
    create_station_price()

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(avg_mpg="0", tank_capacity_gal="16"),
    )

    assert response.status_code == 400
    assert "avg_mpg must be > 0" in response.json()["error"]


@pytest.mark.django_db
def test_optimize_route_rejects_outside_us_coordinates(client):
    create_station_price()

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(
            origin="Mexico City, Mexico",
            destination="Seattle, Washington, United States",
            origin_lat="19.4326",
            origin_lon="-99.1332",
            destination_lat="47.6062",
            destination_lon="-122.3321",
        ),
    )

    assert response.status_code == 400
    assert "supports routes inside the United States only" in response.json()["error"]


@pytest.mark.django_db
def test_optimize_route_accounts_for_starting_fuel_level(client, monkeypatch):
    create_station_price(retail_price=3.150)

    def fake_optimize(
        self,
        origin_query,
        destination_query,
        candidate_stations,
        weights,
        origin_coords,
        destination_coords,
    ):
        station = candidate_stations[0]
        alternative = {
            "station": station,
            "distance_m": 804672.0,  # 500 miles
            "duration_s": 25200.0,
            "geometry": "",
            "estimated_fuel_cost": 63.0,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
        }
        return {
            "origin": {
                "lat": float(origin_coords["lat"]),
                "lon": float(origin_coords["lon"]),
                "display_name": origin_query,
            },
            "destination": {
                "lat": float(destination_coords["lat"]),
                "lon": float(destination_coords["lon"]),
                "display_name": destination_query,
            },
            "best_option": alternative,
            "alternatives": [alternative],
            "weights": weights,
        }

    monkeypatch.setattr(views.RouteOptimizer, "optimize", fake_optimize)

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(
            avg_mpg="25",
            tank_capacity_gal="16",
            start_fuel_percent="10",
        ),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["assumptions"]["start_fuel_percent"] == pytest.approx(10.0)
    assert payload["fuel_plan"]["initial_range_mi"] == pytest.approx(40.0)
    assert payload["fuel_plan"]["min_refuel_stops"] == 2


@pytest.mark.django_db
def test_optimize_route_no_refuel_returns_direct_alternatives(client, monkeypatch):
    create_station_price(retail_price=3.150)

    def fake_optimize(
        self,
        origin_query,
        destination_query,
        candidate_stations,
        weights,
        origin_coords,
        destination_coords,
    ):
        station = candidate_stations[0]
        alternative = {
            "station": station,
            "distance_m": 804672.0,  # 500 miles
            "duration_s": 25200.0,
            "geometry": "",
            "estimated_fuel_cost": 63.0,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
        }
        return {
            "origin": {
                "lat": float(origin_coords["lat"]),
                "lon": float(origin_coords["lon"]),
                "display_name": origin_query,
            },
            "destination": {
                "lat": float(destination_coords["lat"]),
                "lon": float(destination_coords["lon"]),
                "display_name": destination_query,
            },
            "best_option": alternative,
            "alternatives": [alternative],
            "weights": weights,
        }

    direct_alternatives = [
        {
            "station": {
                "id": "direct-1",
                "name": "Direct Route #1",
                "address": "No refuel required",
                "lat": None,
                "lon": None,
                "retail_price": 3.5,
                "synthetic": True,
            },
            "distance_m": 804672.0,
            "duration_s": 25000.0,
            "geometry": [[35.4676, -97.5164], [39.7392, -104.9903]],
            "estimated_fuel_cost": 120.0,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
            "refuel_waypoints": [],
        },
        {
            "station": {
                "id": "direct-2",
                "name": "Direct Route #2",
                "address": "No refuel required",
                "lat": None,
                "lon": None,
                "retail_price": 3.5,
                "synthetic": True,
            },
            "distance_m": 820000.0,
            "duration_s": 26000.0,
            "geometry": [[35.4676, -97.5164], [37.0, -101.0], [39.7392, -104.9903]],
            "estimated_fuel_cost": 123.0,
            "time_norm": 1.0,
            "price_norm": 1.0,
            "score": 1.0,
            "refuel_waypoints": [],
        },
    ]

    monkeypatch.setattr(views.RouteOptimizer, "optimize", fake_optimize)
    monkeypatch.setattr(
        views,
        "build_direct_route_alternatives",
        lambda *args, **kwargs: direct_alternatives,
    )

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(avg_mpg="7", tank_capacity_gal="150", start_fuel_percent="100"),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["fuel_plan"]["min_refuel_stops"] == 0
    assert payload["waypoints"] == []
    assert payload["alternatives"][0]["station"]["name"].startswith("Direct Route #")
    assert len(payload["path"]) == 2


@pytest.mark.django_db
def test_optimize_route_retries_osrm_before_fallback(client, monkeypatch):
    create_station_price(retail_price=3.000)
    calls = {"primary": 0, "retry": 0, "fallback": 0}

    def fail_primary(origin, destination, waypoints=None):
        calls["primary"] += 1
        raise ProviderTimeoutError("OSRM request timed out")

    def succeed_retry(origin, destination, waypoints=None):
        calls["retry"] += 1
        return {
            "distance_m": 160934.4,
            "duration_s": 7200.0,
            "geometry": "retry-geometry",
        }

    def fail_fallback(*args, **kwargs):
        calls["fallback"] += 1
        raise AssertionError("fallback should not run when retry succeeds")

    monkeypatch.setattr(views.DIRECTIONS, "route", fail_primary)
    monkeypatch.setattr(views.DIRECTIONS_RETRY, "route", succeed_retry)
    monkeypatch.setattr(views, "optimize_without_osrm", fail_fallback)

    response = client.get(reverse("stations-optimize"), optimize_query())

    assert response.status_code == 200
    payload = response.json()

    assert payload["engine"] == views.DEFAULT_DIRECTIONS_ENGINE
    assert payload["fuel_cost"] == pytest.approx(12.0)
    assert calls["primary"] >= 1
    assert calls["retry"] >= 1
    assert calls["fallback"] == 0


@pytest.mark.django_db
def test_optimize_route_uses_fallback_after_retry_failure(client, monkeypatch):
    create_station_price(retail_price=3.000)

    def fail_primary(origin, destination, waypoints=None):
        raise ProviderTimeoutError("OSRM request timed out")

    def fail_retry(origin, destination, waypoints=None):
        raise ProviderTimeoutError("OSRM request timed out")

    fallback_call = {"vehicle_mpg": None}

    def fake_fallback(origin_coords, destination_coords, candidates, weights, vehicle_mpg):
        fallback_call["vehicle_mpg"] = vehicle_mpg
        station = candidates[0]
        distance_m = 321868.8
        distance_miles = distance_m / 1609.344
        fuel_cost = (distance_miles / vehicle_mpg) * float(station["retail_price"])

        alternative = {
            "station": station,
            "distance_m": distance_m,
            "duration_s": 15000.0,
            "geometry": "",
            "estimated_fuel_cost": fuel_cost,
            "time_norm": 0.0,
            "price_norm": 0.0,
            "score": 0.0,
        }

        return {
            "origin": origin_coords,
            "destination": destination_coords,
            "best_option": alternative,
            "alternatives": [alternative],
            "weights": weights,
            "engine": "fallback_estimate",
        }

    monkeypatch.setattr(views.DIRECTIONS, "route", fail_primary)
    monkeypatch.setattr(views.DIRECTIONS_RETRY, "route", fail_retry)
    monkeypatch.setattr(views, "optimize_without_osrm", fake_fallback)

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(avg_mpg="40", tank_capacity_gal="18"),
    )

    assert response.status_code == 200
    payload = response.json()

    assert fallback_call["vehicle_mpg"] == pytest.approx(40.0)
    assert payload["engine"] == "fallback_estimate"
    assert payload["assumptions"]["avg_mpg"] == pytest.approx(40.0)
    assert payload["assumptions"]["tank_capacity_gal"] == pytest.approx(18.0)


@pytest.mark.django_db
def test_optimize_route_uses_estimated_labels_for_synthetic_candidates(client, monkeypatch):
    create_station_price(
        retail_price=2.699,
        opis_truckstop_id=1101,
        rack_id=11,
        name="DK",
        city="El Paso",
        state="TX",
    )
    create_station_price(
        retail_price=2.687,
        opis_truckstop_id=1102,
        rack_id=12,
        name="7-ELEVEN #218",
        city="Harrold",
        state="TX",
    )
    create_station_price(
        retail_price=2.749,
        opis_truckstop_id=1103,
        rack_id=13,
        name="CHEVRON",
        city="Vidor",
        state="TX",
    )

    def fake_optimize(
        self,
        origin_query,
        destination_query,
        candidate_stations,
        weights,
        origin_coords,
        destination_coords,
    ):
        assert candidate_stations
        assert all(station.get("synthetic") for station in candidate_stations)

        alternatives = []
        for idx, station in enumerate(candidate_stations):
            alternatives.append(
                {
                    "station": station,
                    "distance_m": 1609344.0 + (idx * 1000.0),
                    "duration_s": 72000.0 + (idx * 60.0),
                    "geometry": "",
                    "estimated_fuel_cost": 15.0 + idx,
                    "time_norm": idx / max(1, len(candidate_stations) - 1),
                    "price_norm": idx / max(1, len(candidate_stations) - 1),
                    "score": idx / max(1, len(candidate_stations) - 1),
                }
            )

        return {
            "origin": {
                "lat": float(origin_coords["lat"]),
                "lon": float(origin_coords["lon"]),
                "display_name": origin_query,
            },
            "destination": {
                "lat": float(destination_coords["lat"]),
                "lon": float(destination_coords["lon"]),
                "display_name": destination_query,
            },
            "best_option": alternatives[0],
            "alternatives": alternatives,
            "weights": weights,
        }

    monkeypatch.setattr(views.RouteOptimizer, "optimize", fake_optimize)

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(
            origin="Boston, Thomas County, Georgia, United States",
            destination="New Jersey, United States",
        ),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["waypoints"]
    for waypoint in payload["waypoints"]:
        assert waypoint["name"].startswith("Estimated Fuel Stop")
        assert waypoint["address"] == "Estimated along route (provider fallback)"

    for alt in payload["alternatives"]:
        assert alt["station"]["synthetic"] is True
        assert alt["station"]["name"].startswith("Estimated Fuel Stop")
        assert alt["station"]["address"] == "Estimated along route (provider fallback)"


@pytest.mark.django_db
def test_optimize_route_uses_real_station_names_and_multi_stop_waypoints(client, monkeypatch):
    create_station_price(
        retail_price=2.899,
        opis_truckstop_id=2101,
        rack_id=21,
        name="Pilot Thomasville",
        city="Thomasville",
        state="GA",
    )
    create_station_price(
        retail_price=2.999,
        opis_truckstop_id=2102,
        rack_id=22,
        name="TA Raleigh",
        city="Raleigh",
        state="NC",
    )
    create_station_price(
        retail_price=3.099,
        opis_truckstop_id=2103,
        rack_id=23,
        name="Flying J Newark",
        city="Newark",
        state="NJ",
    )

    monkeypatch.setattr(views, "MAX_STATION_GEOCODE_ATTEMPTS", 12)

    def fake_station_geocode(query):
        mapping = {
            "Pilot Thomasville": {"lat": 30.84, "lon": -83.98},
            "TA Raleigh": {"lat": 35.78, "lon": -78.64},
            "Flying J Newark": {"lat": 40.73, "lon": -74.17},
        }
        for key, value in mapping.items():
            if key in query:
                return value
        return None

    def fake_optimize(
        self,
        origin_query,
        destination_query,
        candidate_stations,
        weights,
        origin_coords,
        destination_coords,
    ):
        assert candidate_stations
        assert any(not station.get("synthetic") for station in candidate_stations)

        alternatives = []
        for idx, station in enumerate(candidate_stations[:3]):
            alternatives.append(
                {
                    "station": station,
                    "distance_m": 1610000.0 + (idx * 500.0),
                    "duration_s": 73000.0 + (idx * 100.0),
                    "geometry": "",
                    "estimated_fuel_cost": 185.0 + idx,
                    "time_norm": idx / 2,
                    "price_norm": idx / 2,
                    "score": idx / 2,
                }
            )

        return {
            "origin": {
                "lat": float(origin_coords["lat"]),
                "lon": float(origin_coords["lon"]),
                "display_name": origin_query,
            },
            "destination": {
                "lat": float(destination_coords["lat"]),
                "lon": float(destination_coords["lon"]),
                "display_name": destination_query,
            },
            "best_option": alternatives[0],
            "alternatives": alternatives,
            "weights": weights,
        }

    monkeypatch.setattr(views, "geocode_station_cached", fake_station_geocode)
    monkeypatch.setattr(views.RouteOptimizer, "optimize", fake_optimize)

    response = client.get(
        reverse("stations-optimize"),
        optimize_query(
            origin="Boston, Thomas County, Georgia, United States",
            destination="New York, New York, United States",
            origin_lat="30.7919",
            origin_lon="-83.7899",
            destination_lat="40.7128",
            destination_lon="-74.0060",
        ),
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["fuel_plan"]["min_refuel_stops"] == 2
    assert len(payload["waypoints"]) == 2
    assert len(payload["path"]) == 4
    assert any(not wp["name"].startswith("Estimated Fuel Stop") for wp in payload["waypoints"])

    option_names = [alt["station"]["name"] for alt in payload["alternatives"]]
    assert any("Pilot Thomasville" in name for name in option_names)
    assert any("TA Raleigh" in name for name in option_names)
