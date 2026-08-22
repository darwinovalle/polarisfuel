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
