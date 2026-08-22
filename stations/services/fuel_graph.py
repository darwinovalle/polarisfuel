from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RouteNode:
    node_id: str
    kind: str
    lat: float
    lon: float
    fuel_price: float | None = None
    synthetic: bool = False


@dataclass(frozen=True)
class RouteEdge:
    from_node: str
    to_node: str
    distance_m: float
    duration_s: float
    fuel_consumed_gal: float
    detour_m: float = 0.0


@dataclass(frozen=True)
class FuelState:
    remaining_gal: float
    capacity_gal: float

    def __post_init__(self):
        if self.capacity_gal <= 0:
            raise ValueError("fuel capacity must be > 0")
        if self.remaining_gal < 0 or self.remaining_gal > self.capacity_gal:
            raise ValueError("remaining fuel must be within tank capacity")

    def refueled(self) -> "FuelState":
        return FuelState(
            remaining_gal=self.capacity_gal,
            capacity_gal=self.capacity_gal,
        )

    def consume(self, edge: "RouteEdge") -> "FuelState":
        if edge.fuel_consumed_gal > self.remaining_gal + 1e-9:
            raise ValueError("route edge is unreachable with remaining fuel")
        return FuelState(
            remaining_gal=self.remaining_gal - edge.fuel_consumed_gal,
            capacity_gal=self.capacity_gal,
        )


def build_route_edge(
    from_node: RouteNode,
    to_node: RouteNode,
    distance_m: float,
    duration_s: float,
    mpg: float,
    detour_m: float = 0.0,
) -> RouteEdge:
    if distance_m < 0 or duration_s < 0 or detour_m < 0:
        raise ValueError("route edge metrics cannot be negative")
    if mpg <= 0:
        raise ValueError("mpg must be > 0")

    distance_miles = float(distance_m) / 1609.344
    return RouteEdge(
        from_node=from_node.node_id,
        to_node=to_node.node_id,
        distance_m=float(distance_m),
        duration_s=float(duration_s),
        fuel_consumed_gal=distance_miles / float(mpg),
        detour_m=float(detour_m),
    )


def build_route_graph_nodes(
    origin: dict[str, Any],
    destination: dict[str, Any],
    stations: list[dict[str, Any]],
) -> dict[str, RouteNode]:
    nodes = {
        "START": RouteNode(
            node_id="START",
            kind="origin",
            lat=float(origin["lat"]),
            lon=float(origin["lon"]),
        ),
        "END": RouteNode(
            node_id="END",
            kind="destination",
            lat=float(destination["lat"]),
            lon=float(destination["lon"]),
        ),
    }

    for station in stations:
        station_id = str(station["id"])
        if station_id in nodes:
            raise ValueError(f"duplicate route graph node id: {station_id}")

        nodes[station_id] = RouteNode(
            node_id=station_id,
            kind="station",
            lat=float(station["lat"]),
            lon=float(station["lon"]),
            fuel_price=float(station["retail_price"]),
            synthetic=bool(station.get("synthetic", False)),
        )

    return nodes
