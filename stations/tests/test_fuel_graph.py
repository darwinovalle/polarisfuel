import pytest

from stations.services.fuel_graph import RouteNode, build_route_graph_nodes


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
