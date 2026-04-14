import pytest

from stations.services.route_optimizer import RouteOptimizer


class FakeGeocodingProvider:
    def geocode(self, query: str) -> dict:
        mapping = {
            "Dallas, TX": {"lat": 32.7767, "lon": -96.7970, "display_name": "Dallas"},
            "New York, NY": {"lat": 40.7128, "lon": -74.0060, "display_name": "New York"},
        }
        return mapping[query]


class FakeDirectionsProvider:
    def route(self, origin: dict, destination: dict, waypoints=None) -> dict:
        waypoints = waypoints or []

        # Baseline direct route
        if not waypoints:
            return {
                "distance_m": 2500000.0,
                "duration_s": 100000.0,
                "geometry": "baseline",
            }

        stop = waypoints[0]
        station_id = stop["id"]

        if station_id == "A":
            # slower, cheaper
            return {"distance_m": 2550000.0, "duration_s": 103000.0, "geometry": "route-A"}
        if station_id == "B":
            # faster, expensive
            return {"distance_m": 2520000.0, "duration_s": 101000.0, "geometry": "route-B"}
        if station_id == "C":
            # worst
            return {"distance_m": 2600000.0, "duration_s": 106000.0, "geometry": "route-C"}

        raise ValueError("Unknown station id")


@pytest.fixture
def candidate_stations():
    return [
        {"id": "A", "name": "Pilot A", "lat": 33.0, "lon": -95.0, "retail_price": 3.20},
        {"id": "B", "name": "TA B", "lat": 34.0, "lon": -94.0, "retail_price": 4.20},
        {"id": "C", "name": "Love C", "lat": 35.0, "lon": -93.0, "retail_price": 4.80},
    ]


def build_optimizer():
    return RouteOptimizer(
        geocoding_provider=FakeGeocodingProvider(),
        directions_provider=FakeDirectionsProvider(),
        vehicle_km_per_liter=3.0,
    )


@pytest.mark.django_db
def test_optimize_route_returns_ranked_alternatives(candidate_stations):
    optimizer = build_optimizer()

    result = optimizer.optimize(
        origin_query="Dallas, TX",
        destination_query="New York, NY",
        candidate_stations=candidate_stations,
        weights={"time": 0.6, "price": 0.4},
    )

    assert "best_option" in result
    assert "alternatives" in result
    assert len(result["alternatives"]) == 3

    scores = [x["score"] for x in result["alternatives"]]
    assert scores == sorted(scores)


@pytest.mark.django_db
def test_optimize_route_time_heavy_weight_prefers_faster(candidate_stations):
    optimizer = build_optimizer()

    result = optimizer.optimize(
        origin_query="Dallas, TX",
        destination_query="New York, NY",
        candidate_stations=candidate_stations,
        weights={"time": 0.9, "price": 0.1},
    )

    assert result["best_option"]["station"]["id"] == "B"


@pytest.mark.django_db
def test_optimize_route_price_heavy_weight_prefers_cheaper(candidate_stations):
    optimizer = build_optimizer()

    result = optimizer.optimize(
        origin_query="Dallas, TX",
        destination_query="New York, NY",
        candidate_stations=candidate_stations,
        weights={"time": 0.1, "price": 0.9},
    )

    assert result["best_option"]["station"]["id"] == "A"


@pytest.mark.django_db
def test_optimize_route_raises_on_empty_candidates():
    optimizer = build_optimizer()

    with pytest.raises(ValueError):
        optimizer.optimize(
            origin_query="Dallas, TX",
            destination_query="New York, NY",
            candidate_stations=[],
            weights={"time": 0.5, "price": 0.5},
        )


@pytest.mark.django_db
def test_output_contains_score_breakdown(candidate_stations):
    optimizer = build_optimizer()

    result = optimizer.optimize(
        origin_query="Dallas, TX",
        destination_query="New York, NY",
        candidate_stations=candidate_stations,
        weights={"time": 0.5, "price": 0.5},
    )

    first = result["alternatives"][0]
    assert "time_norm" in first
    assert "price_norm" in first
    assert "score" in first
    assert "distance_m" in first
    assert "duration_s" in first
    assert "estimated_fuel_cost" in first
