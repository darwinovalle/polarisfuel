import pytest

from stations.services.fuel_graph import (
    RouteNode,
    build_route_edge,
    build_route_graph_nodes,
)


def test_build_route_graph_nodes_includes_endpoints_and_stations():
    nodes = build_route_graph_nodes(
        origin={"lat": 32.0, "lon": -96.0},
        destination={"lat": 35.0, "lon": -90.0},
        stations=[
            {
                "id": "station-a",
                "lat": 33.0,
                "lon": -94.0,
                "retail_price": 3.25,
                "synthetic": False,
            }
        ],
    )

    assert nodes["START"] == RouteNode("START", "origin", 32.0, -96.0)
    assert nodes["END"].kind == "destination"
    assert nodes["station-a"].kind == "station"
    assert nodes["station-a"].fuel_price == pytest.approx(3.25)
    assert nodes["station-a"].synthetic is False


def test_build_route_graph_nodes_rejects_duplicate_endpoint_id():
    with pytest.raises(ValueError, match="duplicate route graph node id"):
        build_route_graph_nodes(
            origin={"lat": 32.0, "lon": -96.0},
            destination={"lat": 35.0, "lon": -90.0},
            stations=[
                {
                    "id": "START",
                    "lat": 33.0,
                    "lon": -94.0,
                    "retail_price": 3.25,
                }
            ],
        )


def test_build_route_edge_calculates_fuel_and_detour_metrics():
    start = RouteNode("START", "origin", 32.0, -96.0)
    station = RouteNode("station-a", "station", 33.0, -94.0, fuel_price=3.25)

    edge = build_route_edge(
        from_node=start,
        to_node=station,
        distance_m=1609344.0,
        duration_s=3600.0,
        mpg=25.0,
        detour_m=8046.72,
    )

    assert edge.from_node == "START"
    assert edge.to_node == "station-a"
    assert edge.fuel_consumed_gal == pytest.approx(40.0)
    assert edge.detour_m == pytest.approx(8046.72)


def test_build_route_edge_rejects_invalid_metrics():
    start = RouteNode("START", "origin", 32.0, -96.0)
    end = RouteNode("END", "destination", 35.0, -90.0)

    with pytest.raises(ValueError, match="mpg"):
        build_route_edge(start, end, 1000.0, 60.0, mpg=0.0)

    with pytest.raises(ValueError, match="cannot be negative"):
        build_route_edge(start, end, -1.0, 60.0, mpg=25.0)
