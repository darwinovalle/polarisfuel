import pytest

from stations import views


class FullRouteFailsProvider:
    def __init__(self):
        self.full_calls = 0
        self.segment_calls = 0

    def route(self, origin: dict, destination: dict, waypoints=None) -> dict:
        waypoints = waypoints or []
        if waypoints:
            self.full_calls += 1
            raise RuntimeError("full multi-waypoint route failed")

        self.segment_calls += 1
        return {
            "distance_m": 1000.0,
            "duration_s": 120.0,
            "geometry": [
                [float(origin["lat"]), float(origin["lon"])],
                [
                    (float(origin["lat"]) + float(destination["lat"])) / 2.0,
                    (float(origin["lon"]) + float(destination["lon"])) / 2.0,
                ],
                [float(destination["lat"]), float(destination["lon"])],
            ],
        }


def test_build_route_geometry_path_stitches_segment_routes(monkeypatch):
    provider = FullRouteFailsProvider()

    monkeypatch.setattr(views, "PATH_DIRECTIONS", provider)
    monkeypatch.setattr(views, "PATH_DIRECTIONS_RETRY", provider)

    origin = {"lat": 10.0, "lon": -100.0}
    destination = {"lat": 20.0, "lon": -90.0}
    waypoints = [
        {"lat": 13.0, "lng": -97.0},
        {"lat": 16.0, "lng": -94.0},
    ]

    path = views.build_route_geometry_path(origin, destination, waypoints)

    # Should not fall back to straight-line [origin, waypoints..., destination].
    assert len(path) > (len(waypoints) + 2)
    assert provider.full_calls >= 1
    assert provider.segment_calls >= (len(waypoints) + 1)


def test_build_alternative_refuel_previews_builds_distinct_option_paths(monkeypatch):
    def fake_path_builder(origin_coords, destination_coords, waypoints):
        path = [[float(origin_coords["lat"]), float(origin_coords["lon"])]]
        path.extend([[float(wp["lat"]), float(wp["lng"])] for wp in waypoints])
        path.append([float(destination_coords["lat"]), float(destination_coords["lon"])])
        return path

    monkeypatch.setattr(views, "build_route_geometry_path", fake_path_builder)

    alternatives = [
        {
            "station": {
                "name": "Station A",
                "address": "Addr A",
                "lat": 35.0,
                "lon": -118.0,
            },
            "distance_m": 1000.0,
            "duration_s": 120.0,
            "estimated_fuel_cost": 50.0,
            "score": 0.1,
            "geometry": [],
        },
        {
            "station": {
                "name": "Station B",
                "address": "Addr B",
                "lat": 40.0,
                "lon": -121.0,
            },
            "distance_m": 1200.0,
            "duration_s": 140.0,
            "estimated_fuel_cost": 60.0,
            "score": 0.2,
            "geometry": [],
        },
    ]

    shared_waypoints = [
        {"lat": 39.5, "lng": -120.5, "name": "Shared 1", "address": "S1", "type": "Refuel Stop 1"},
        {"lat": 34.9, "lng": -117.9, "name": "Shared 2", "address": "S2", "type": "Refuel Stop 2"},
    ]

    enriched = views.build_alternative_refuel_previews(
        alternatives=alternatives,
        origin_coords={"lat": 47.6, "lon": -122.3},
        destination_coords={"lat": 32.7, "lon": -117.1},
        shared_waypoints=shared_waypoints,
    )

    assert len(enriched) == 2
    assert "refuel_waypoints" in enriched[0]
    assert "refuel_waypoints" in enriched[1]
    assert len(enriched[0]["geometry"]) >= 3
    assert len(enriched[1]["geometry"]) >= 3
    # Option-specific station substitution should yield different paths.
    assert enriched[0]["geometry"] != enriched[1]["geometry"]


def test_select_refuel_waypoints_are_ordered_and_fuel_feasible():
    station_pool = [
        {"id": "a", "name": "A", "address": "", "lat": 10.5, "lon": -99.5, "retail_price": 3.2, "progress_ratio": 0.10, "corridor_distance_m": 2000.0, "synthetic": False},
        {"id": "b", "name": "B", "address": "", "lat": 12.0, "lon": -98.0, "retail_price": 3.1, "progress_ratio": 0.30, "corridor_distance_m": 1000.0, "synthetic": False},
        {"id": "c", "name": "C", "address": "", "lat": 13.5, "lon": -96.5, "retail_price": 3.0, "progress_ratio": 0.55, "corridor_distance_m": 1100.0, "synthetic": False},
        {"id": "d", "name": "D", "address": "", "lat": 15.0, "lon": -95.0, "retail_price": 2.9, "progress_ratio": 0.80, "corridor_distance_m": 1300.0, "synthetic": False},
    ]

    selected = views.select_refuel_waypoints(
        origin_coords={"lat": 10.0, "lon": -100.0},
        destination_coords={"lat": 16.0, "lon": -94.0},
        station_pool=station_pool,
        required_stops=2,
        initial_reach_ratio=0.45,
        max_leg_ratio=0.45,
    )

    assert len(selected) == 2
    progresses = [float(stop["progress_ratio"]) for stop in selected]
    assert progresses == sorted(progresses)
    # First stop should be reachable from initial fuel range with small tolerance.
    assert progresses[0] <= 0.55


def test_select_refuel_waypoints_prefers_cheapest_station_after_halfway():
    station_pool = [
        {"id": "near", "name": "Near", "lat": 10.5, "lon": -99.5, "retail_price": 2.0, "progress_ratio": 0.25, "corridor_distance_m": 500.0, "synthetic": False},
        {"id": "mid", "name": "Mid", "lat": 13.0, "lon": -97.0, "retail_price": 3.5, "progress_ratio": 0.55, "corridor_distance_m": 500.0, "synthetic": False},
        {"id": "cheap", "name": "Cheap", "lat": 14.0, "lon": -96.0, "retail_price": 2.5, "progress_ratio": 0.70, "corridor_distance_m": 500.0, "synthetic": False},
    ]

    selected = views.select_refuel_waypoints(
        origin_coords={"lat": 10.0, "lon": -100.0},
        destination_coords={"lat": 16.0, "lon": -94.0},
        station_pool=station_pool,
        required_stops=1,
        initial_reach_ratio=0.80,
        max_leg_ratio=0.80,
    )

    assert selected[0]["station_id"] == "cheap"


def test_distance_to_polyline_follows_route_shape():
    straight_distance = views.distance_point_to_segment_m(
        point_lat=1.0,
        point_lon=5.0,
        origin_lat=0.0,
        origin_lon=0.0,
        destination_lat=10.0,
        destination_lon=10.0,
    )
    route_distance = views.distance_point_to_polyline_m(
        point_lat=1.0,
        point_lon=5.0,
        polyline=[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0]],
    )

    assert route_distance < straight_distance


def test_build_route_segments_orders_stops_and_exposes_both_leg_distances():
    segments = views.build_route_segments(
        origin={"lat": 0.0, "lon": 0.0},
        destination={"lat": 0.0, "lon": 10.0},
        stops=[
            {"name": "Second", "lat": 0.0, "lng": 8.0, "progress_ratio": 0.8},
            {"name": "First", "lat": 0.0, "lng": 3.0, "progress_ratio": 0.3},
        ],
        route_geometry=[[0.0, 0.0], [0.0, 10.0]],
        route_distance_m=100000.0,
    )

    assert [stop["name"] for stop in segments["stops"]] == ["First", "Second"]
    assert segments["stops"][0]["distance_from_previous_m"] == pytest.approx(30000.0)
    assert segments["stops"][0]["distance_to_next_m"] == pytest.approx(70000.0)
    assert segments["stops"][1]["distance_from_previous_m"] == pytest.approx(50000.0)
    assert segments["stops"][1]["distance_to_next_m"] == pytest.approx(20000.0)
    assert segments["destination_distance_m"] == pytest.approx(20000.0)


class DirectAlternativesProvider:
    def route(self, origin, destination, waypoints=None, include_alternatives=False):
        assert not waypoints
        return {
            "alternatives": [
                {
                    "distance_m": 1609344.0,
                    "duration_s": 1000.0,
                    "geometry": [[origin["lat"], origin["lon"]], [destination["lat"], destination["lon"]]],
                },
                {
                    "distance_m": 1931212.8,
                    "duration_s": 1200.0,
                    "geometry": [[origin["lat"], origin["lon"]], [destination["lat"], destination["lon"]]],
                },
            ]
        }


def test_direct_route_alternatives_apply_time_and_price_weights(monkeypatch):
    provider = DirectAlternativesProvider()
    monkeypatch.setattr(views, "PATH_DIRECTIONS", provider)
    monkeypatch.setattr(views, "PATH_DIRECTIONS_RETRY", None)

    common = {
        "origin_coords": {"lat": 32.0, "lon": -96.0},
        "destination_coords": {"lat": 35.0, "lon": -90.0},
        "vehicle_mpg": 25.0,
        "reference_fuel_price": 3.5,
        "max_options": 2,
    }

    fastest = views.build_direct_route_alternatives(
        **common,
        weights={"time": 1.0, "price": 0.0},
    )
    cheapest = views.build_direct_route_alternatives(
        **common,
        weights={"time": 0.0, "price": 1.0},
    )

    assert fastest[0]["duration_s"] == 1000.0
    assert cheapest[0]["distance_m"] == 1609344.0
    assert cheapest[0]["fuel_plan"]["tank_capacity_gal"] == pytest.approx(16.0)
    assert cheapest[0]["fuel_plan"]["start_fuel_percent"] == pytest.approx(100.0)
