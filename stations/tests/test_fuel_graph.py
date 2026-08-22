import pytest

from stations.services.fuel_graph import (
    FuelState,
    RouteNode,
    build_route_edge,
    build_route_graph_nodes,
    calculate_refuel_purchase,
    search_feasible_route_plans,
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


def test_fuel_state_consumes_and_refuels_at_capacity():
    start = RouteNode("START", "origin", 32.0, -96.0)
    station = RouteNode("station-a", "station", 33.0, -94.0, fuel_price=3.25)
    edge = build_route_edge(start, station, 160934.4, 3600.0, mpg=25.0)
    state = FuelState(remaining_gal=8.0, capacity_gal=16.0)

    after_leg = state.consume(edge)

    assert after_leg.remaining_gal == pytest.approx(4.0)
    assert after_leg.refueled().remaining_gal == pytest.approx(16.0)


def test_fuel_state_rejects_unreachable_leg():
    start = RouteNode("START", "origin", 32.0, -96.0)
    end = RouteNode("END", "destination", 35.0, -90.0)
    edge = build_route_edge(start, end, 482803.2, 3600.0, mpg=25.0)

    with pytest.raises(ValueError, match="unreachable"):
        FuelState(remaining_gal=10.0, capacity_gal=16.0).consume(edge)


def test_calculate_refuel_purchase_uses_station_price():
    state = FuelState(remaining_gal=4.0, capacity_gal=16.0)

    refueled, gallons, cost = calculate_refuel_purchase(state, fuel_price=3.25)

    assert refueled.remaining_gal == pytest.approx(16.0)
    assert gallons == pytest.approx(12.0)
    assert cost == pytest.approx(39.0)


def test_calculate_refuel_purchase_rejects_negative_price():
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_refuel_purchase(FuelState(4.0, 16.0), fuel_price=-1.0)


def test_search_feasible_route_plans_tracks_station_purchase():
    nodes = build_route_graph_nodes(
        origin={"lat": 0.0, "lon": 0.0},
        destination={"lat": 0.0, "lon": 3.0},
        stations=[
            {"id": "cheap", "lat": 0.0, "lon": 1.0, "retail_price": 3.0},
            {"id": "far", "lat": 0.0, "lon": 2.0, "retail_price": 4.0},
        ],
    )
    mpg = 10.0
    edges = [
        build_route_edge(nodes["START"], nodes["cheap"], 32186.88, 100.0, mpg),
        build_route_edge(nodes["cheap"], nodes["END"], 64373.76, 200.0, mpg),
        build_route_edge(nodes["START"], nodes["far"], 64373.76, 200.0, mpg),
        build_route_edge(nodes["far"], nodes["END"], 32186.88, 100.0, mpg),
        build_route_edge(nodes["START"], nodes["END"], 96560.64, 300.0, mpg),
    ]

    plans = search_feasible_route_plans(
        nodes,
        edges,
        FuelState(remaining_gal=4.0, capacity_gal=16.0),
    )

    cheap_plan = next(plan for plan in plans if plan.node_ids == ("START", "cheap", "END"))
    assert cheap_plan.distance_m == pytest.approx(96560.64)
    assert cheap_plan.fuel_purchases[0]["station_id"] == "cheap"
    assert cheap_plan.fuel_purchases[0]["gallons"] == pytest.approx(14.0)
    assert cheap_plan.fuel_cost == pytest.approx(42.0)


def test_search_feasibility_changes_with_mpg():
    nodes = build_route_graph_nodes(
        origin={"lat": 0.0, "lon": 0.0},
        destination={"lat": 0.0, "lon": 1.0},
        stations=[],
    )
    edge = build_route_edge(nodes["START"], nodes["END"], 80467.2, 100.0, mpg=10.0)

    efficient = search_feasible_route_plans(
        nodes, [edge], FuelState(remaining_gal=8.0, capacity_gal=8.0)
    )
    inefficient_edge = build_route_edge(
        nodes["START"], nodes["END"], 80467.2, 100.0, mpg=5.0
    )
    inefficient = search_feasible_route_plans(
        nodes,
        [inefficient_edge],
        FuelState(remaining_gal=8.0, capacity_gal=8.0),
    )

    assert len(efficient) == 1
    assert inefficient == []


def test_search_feasibility_changes_with_tank_capacity():
    nodes = build_route_graph_nodes(
        origin={"lat": 0.0, "lon": 0.0},
        destination={"lat": 0.0, "lon": 2.0},
        stations=[{"id": "A", "lat": 0.0, "lon": 1.0, "retail_price": 3.0}],
    )
    edges = [
        build_route_edge(nodes["START"], nodes["A"], 96560.64, 100.0, mpg=10.0),
        build_route_edge(nodes["A"], nodes["END"], 177027.84, 100.0, mpg=10.0),
    ]

    small_tank = search_feasible_route_plans(
        nodes, edges, FuelState(remaining_gal=10.0, capacity_gal=10.0)
    )
    large_tank = search_feasible_route_plans(
        nodes, edges, FuelState(remaining_gal=10.0, capacity_gal=16.0)
    )

    assert small_tank == []
    assert len(large_tank) == 1


def test_search_feasibility_changes_with_starting_fuel():
    nodes = build_route_graph_nodes(
        origin={"lat": 0.0, "lon": 0.0},
        destination={"lat": 0.0, "lon": 1.0},
        stations=[{"id": "A", "lat": 0.0, "lon": 0.5, "retail_price": 3.0}],
    )
    edges = [
        build_route_edge(nodes["START"], nodes["A"], 80467.2, 100.0, mpg=10.0),
        build_route_edge(nodes["A"], nodes["END"], 80467.2, 100.0, mpg=10.0),
    ]

    low_start = search_feasible_route_plans(
        nodes, edges, FuelState(remaining_gal=1.0, capacity_gal=10.0)
    )
    high_start = search_feasible_route_plans(
        nodes, edges, FuelState(remaining_gal=8.0, capacity_gal=10.0)
    )

    assert low_start == []
    assert len(high_start) == 1
