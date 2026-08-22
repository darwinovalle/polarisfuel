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
    geometry: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class FuelRoutePlan:
    node_ids: tuple[str, ...]
    edges: tuple[RouteEdge, ...]
    distance_m: float
    duration_s: float
    detour_m: float
    fuel_cost: float
    fuel_purchases: tuple[dict[str, float | str], ...]


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


def calculate_refuel_purchase(
    state: FuelState,
    fuel_price: float,
) -> tuple[FuelState, float, float]:
    if fuel_price < 0:
        raise ValueError("fuel price cannot be negative")

    gallons_purchased = state.capacity_gal - state.remaining_gal
    return (
        state.refueled(),
        gallons_purchased,
        gallons_purchased * float(fuel_price),
    )


def search_feasible_route_plans(
    nodes: dict[str, RouteNode],
    edges: list[RouteEdge],
    initial_state: FuelState,
    max_plans: int = 100,
) -> list[FuelRoutePlan]:
    """Enumerate complete, fuel-feasible simple paths from START to END."""
    if "START" not in nodes or "END" not in nodes:
        raise ValueError("route graph must contain START and END nodes")
    if max_plans <= 0:
        raise ValueError("max_plans must be > 0")

    outgoing: dict[str, list[RouteEdge]] = {}
    for edge in edges:
        if edge.from_node not in nodes or edge.to_node not in nodes:
            raise ValueError("route edge references an unknown node")
        outgoing.setdefault(edge.from_node, []).append(edge)

    plans: list[FuelRoutePlan] = []

    def visit(
        node_id: str,
        state: FuelState,
        path: tuple[str, ...],
        path_edges: tuple[RouteEdge, ...],
        purchases: tuple[dict[str, float | str], ...],
        distance_m: float,
        duration_s: float,
        detour_m: float,
        fuel_cost: float,
    ) -> None:
        if len(plans) >= max_plans:
            return
        if node_id == "END":
            plans.append(
                FuelRoutePlan(
                    node_ids=path,
                    edges=path_edges,
                    distance_m=distance_m,
                    duration_s=duration_s,
                    detour_m=detour_m,
                    fuel_cost=fuel_cost,
                    fuel_purchases=purchases,
                )
            )
            return

        for edge in sorted(outgoing.get(node_id, []), key=lambda item: item.to_node):
            if edge.to_node in path:
                continue
            try:
                next_state = state.consume(edge)
            except ValueError:
                continue

            next_purchases = purchases
            next_cost = fuel_cost
            destination = nodes[edge.to_node]
            if destination.kind == "station":
                if destination.fuel_price is None:
                    raise ValueError(f"station {destination.node_id} has no fuel price")
                next_state, gallons, purchase_cost = calculate_refuel_purchase(
                    next_state,
                    destination.fuel_price,
                )
                next_purchases = purchases + (
                    {
                        "station_id": destination.node_id,
                        "gallons": gallons,
                        "cost": purchase_cost,
                    },
                )
                next_cost += purchase_cost

            visit(
                edge.to_node,
                next_state,
                path + (edge.to_node,),
                path_edges + (edge,),
                next_purchases,
                distance_m + edge.distance_m,
                duration_s + edge.duration_s,
                detour_m + edge.detour_m,
                next_cost,
            )

    visit(
        "START",
        initial_state,
        ("START",),
        (),
        (),
        0.0,
        0.0,
        0.0,
        0.0,
    )
    return plans


def build_route_edge(
    from_node: RouteNode,
    to_node: RouteNode,
    distance_m: float,
    duration_s: float,
    mpg: float,
    detour_m: float = 0.0,
    geometry: list | tuple = (),
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
        geometry=tuple(
            (float(point[0]), float(point[1]))
            for point in geometry
            if isinstance(point, (list, tuple)) and len(point) >= 2
        ),
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
