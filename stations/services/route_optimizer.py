from __future__ import annotations

import heapq
from typing import Any

from stations.processes.fuel import calculate_fuel_metrics
from stations.services.fuel_graph import (
    FuelState,
    RouteEdge,
    build_route_edge,
    build_route_graph_nodes,
    search_feasible_route_plans,
)
from stations.services.provider_errors import ProviderUnavailableError


class RouteOptimizer:
    def __init__(
        self,
        geocoding_provider,
        directions_provider,
        vehicle_km_per_liter: float = 3.0,
        vehicle_miles_per_gallon: float | None = None,
        tank_capacity_gal: float = 16.0,
        start_fuel_percent: float = 100.0,
    ):
        if vehicle_miles_per_gallon is None:
            if vehicle_km_per_liter <= 0:
                raise ValueError("vehicle_km_per_liter must be > 0")
            # Backward compatibility: convert km/L to MPG.
            vehicle_miles_per_gallon = float(vehicle_km_per_liter) * 2.352145833

        if vehicle_miles_per_gallon <= 0:
            raise ValueError("vehicle_miles_per_gallon must be > 0")

        self.geocoding_provider = geocoding_provider
        self.directions_provider = directions_provider
        self.vehicle_miles_per_gallon = float(vehicle_miles_per_gallon)
        self.vehicle_km_per_liter = self.vehicle_miles_per_gallon / 2.352145833
        self.tank_capacity_gal = float(tank_capacity_gal)
        self.start_fuel_percent = float(start_fuel_percent)

    def optimize(
        self,
        origin_query: str,
        destination_query: str,
        candidate_stations: list[dict[str, Any]],
        weights: dict[str, float] | None = None,
        origin_coords: dict[str, Any] | None = None,
        destination_coords: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not candidate_stations:
            raise ValueError("candidate_stations cannot be empty")

        weights = self._normalize_weights(weights)

        if origin_coords is not None and destination_coords is not None:
            origin = self._normalize_coordinate(origin_coords, origin_query)
            destination = self._normalize_coordinate(destination_coords, destination_query)
        else:
            origin = self.geocoding_provider.geocode(origin_query)
            destination = self.geocoding_provider.geocode(destination_query)

        alternatives: list[dict[str, Any]] = []
        for station in candidate_stations:
            waypoint = {
                "id": station["id"],
                "lat": station["lat"],
                "lon": station["lon"],
            }

            try:
                route_data = self.directions_provider.route(origin, destination, waypoints=[waypoint])
            except Exception:
                # Skip unroutable candidate stops and keep evaluating the rest.
                continue

            distance_m = float(route_data["distance_m"])
            duration_s = float(route_data["duration_s"])
            station_price = float(station["retail_price"])
            estimated_fuel_cost = self._estimate_fuel_cost(distance_m, station_price)
            fuel_metrics = calculate_fuel_metrics(
                distance_m=distance_m,
                mpg=self.vehicle_miles_per_gallon,
                tank_capacity_gal=self.tank_capacity_gal,
                start_fuel_percent=self.start_fuel_percent,
            )

            alternatives.append(
                {
                    "station": station,
                    "distance_m": distance_m,
                    "duration_s": duration_s,
                    "geometry": route_data.get("geometry", ""),
                    "estimated_fuel_cost": estimated_fuel_cost,
                    "fuel_plan": fuel_metrics,
                }
            )

        if not alternatives:
            raise ProviderUnavailableError("No routable station alternatives available")

        multi_stop_plans = self._build_multi_stop_plans(
            origin=origin,
            destination=destination,
            candidate_stations=candidate_stations,
        )
        if multi_stop_plans:
            reference_price = sum(
                float(station["retail_price"]) for station in candidate_stations
            ) / len(candidate_stations)
            plan_alternatives = [
                self._plan_to_alternative(plan, candidate_stations, reference_price)
                for plan in multi_stop_plans
            ]
            self._apply_scores(plan_alternatives, weights, cost_key="fuel_cost")
            plan_alternatives.sort(key=lambda item: item["score"])
            best_plan = plan_alternatives[0]
            return {
                "origin": origin,
                "destination": destination,
                "baseline_route": None,
                "weights": weights,
                "best_option": best_plan,
                "alternatives": plan_alternatives,
                "multi_stop_plans": plan_alternatives,
                "multi_stop_search_used": True,
                "multi_stop_plan_count": len(plan_alternatives),
                "best_path": best_plan["node_ids"],
                "best_path_cost": best_plan["score"],
            }

        self._apply_scores(alternatives, weights)
        alternatives.sort(key=lambda x: x["score"])

        graph = self._build_station_graph(alternatives)
        best_cost, best_path = self._dijkstra_shortest_path(graph, "START", "END")
        best_station_id = best_path[1] if len(best_path) >= 3 else None

        if best_station_id is None:
            best_option = alternatives[0]
        else:
            best_option = next(
                (item for item in alternatives if str(item["station"]["id"]) == best_station_id),
                alternatives[0],
            )

        return {
            "origin": origin,
            "destination": destination,
            "baseline_route": None,
            "weights": weights,
            "best_option": best_option,
            "alternatives": alternatives,
            "best_path": best_path,
            "best_path_cost": best_cost,
            "multi_stop_search_used": False,
            "multi_stop_plan_count": 0,
        }

    def _build_multi_stop_plans(
        self,
        origin: dict[str, Any],
        destination: dict[str, Any],
        candidate_stations: list[dict[str, Any]],
    ):
        nodes = build_route_graph_nodes(origin, destination, candidate_stations)
        edges: list[RouteEdge] = []
        node_list = list(nodes.values())

        for from_node in node_list:
            for to_node in node_list:
                if from_node.node_id == to_node.node_id:
                    continue
                try:
                    route_data = self.directions_provider.route(
                        {"lat": from_node.lat, "lon": from_node.lon},
                        {"lat": to_node.lat, "lon": to_node.lon},
                        waypoints=[],
                    )
                    edges.append(
                        build_route_edge(
                            from_node=from_node,
                            to_node=to_node,
                            distance_m=float(route_data["distance_m"]),
                            duration_s=float(route_data["duration_s"]),
                            mpg=self.vehicle_miles_per_gallon,
                            detour_m=float(route_data.get("detour_m", 0.0)),
                        )
                    )
                except Exception:
                    continue

        initial_state = FuelState(
            remaining_gal=(
                self.tank_capacity_gal * self.start_fuel_percent / 100.0
            ),
            capacity_gal=self.tank_capacity_gal,
        )
        return search_feasible_route_plans(nodes, edges, initial_state)

    @staticmethod
    def _plan_to_alternative(plan, candidate_stations, reference_price):
        stations_by_id = {str(item["id"]): item for item in candidate_stations}
        stop_ids = [node_id for node_id in plan.node_ids[1:-1]]
        stops = [stations_by_id[node_id] for node_id in stop_ids]
        fuel_cost = plan.fuel_cost
        if not stops:
            fuel_cost = sum(edge.fuel_consumed_gal for edge in plan.edges) * reference_price
        return {
            "station": stops[0] if stops else {
                "id": "direct",
                "name": "Direct Route",
                "retail_price": 0.0,
                "synthetic": False,
            },
            "stations": stops,
            "node_ids": list(plan.node_ids),
            "distance_m": plan.distance_m,
            "duration_s": plan.duration_s,
            "detour_m": plan.detour_m,
            "fuel_cost": fuel_cost,
            "estimated_fuel_cost": fuel_cost,
            "fuel_purchases": list(plan.fuel_purchases),
            "edge_metrics": [
                {
                    "from_node": edge.from_node,
                    "to_node": edge.to_node,
                    "distance_m": edge.distance_m,
                    "duration_s": edge.duration_s,
                    "fuel_consumed_gal": edge.fuel_consumed_gal,
                    "detour_m": edge.detour_m,
                }
                for edge in plan.edges
            ],
            "stop_count": len(stops),
            "refuel_waypoints": stops,
            "geometry": "",
        }

    @staticmethod
    def _normalize_coordinate(value: dict[str, Any], default_name: str) -> dict[str, Any]:
        try:
            lat = float(value["lat"])
            lon = float(value["lon"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid coordinate payload") from exc

        return {
            "lat": lat,
            "lon": lon,
            "display_name": value.get("display_name", default_name),
        }

    def _estimate_fuel_cost(self, distance_m: float, retail_price: float) -> float:
        # Retail price is USD per gallon, so use miles and MPG.
        distance_miles = distance_m / 1609.344
        gallons_needed = distance_miles / self.vehicle_miles_per_gallon
        return gallons_needed * retail_price

    def _apply_scores(
        self,
        alternatives: list[dict[str, Any]],
        weights: dict[str, float],
        cost_key: str = "estimated_fuel_cost",
    ) -> None:
        durations = [x["duration_s"] for x in alternatives]
        prices = [x[cost_key] for x in alternatives]

        min_d, max_d = min(durations), max(durations)
        min_p, max_p = min(prices), max(prices)

        for item in alternatives:
            time_norm = self._min_max_norm(item["duration_s"], min_d, max_d)
            price_norm = self._min_max_norm(item[cost_key], min_p, max_p)
            score = (weights["time"] * time_norm) + (weights["price"] * price_norm)

            item["time_norm"] = time_norm
            item["price_norm"] = price_norm
            item["score"] = score

    @staticmethod
    def _build_station_graph(alternatives: list[dict[str, Any]]) -> dict[str, list[tuple[str, float]]]:
        graph: dict[str, list[tuple[str, float]]] = {"START": [], "END": []}

        for item in alternatives:
            station_id = str(item["station"]["id"])
            graph["START"].append((station_id, float(item["score"])))
            graph[station_id] = [("END", 0.0)]

        graph["START"] = sorted(graph["START"], key=lambda x: x[0])
        return graph

    @staticmethod
    def _dijkstra_shortest_path(
        graph: dict[str, list[tuple[str, float]]],
        start: str,
        end: str,
    ) -> tuple[float, list[str]]:
        if start not in graph or end not in graph:
            raise ValueError("start or end node not in graph")

        pq: list[tuple[float, tuple[str, ...], str]] = []
        heapq.heappush(pq, (0.0, (start,), start))

        best: dict[str, tuple[float, tuple[str, ...]]] = {start: (0.0, (start,))}

        while pq:
            cost, path, node = heapq.heappop(pq)

            if node == end:
                return cost, list(path)

            known = best.get(node)
            if known is None:
                continue

            if cost > known[0] or (cost == known[0] and path > known[1]):
                continue

            for neighbor, weight in sorted(graph.get(node, []), key=lambda x: x[0]):
                if weight < 0:
                    raise ValueError("Dijkstra requires non-negative weights")

                new_cost = cost + float(weight)
                new_path = path + (neighbor,)

                candidate = (new_cost, new_path)
                current = best.get(neighbor)

                if current is None or candidate < current:
                    best[neighbor] = candidate
                    heapq.heappush(pq, (new_cost, new_path, neighbor))

        raise ValueError("No path found")

    @staticmethod
    def _min_max_norm(value: float, min_value: float, max_value: float) -> float:
        if max_value == min_value:
            return 0.0
        return (value - min_value) / (max_value - min_value)

    @staticmethod
    def _normalize_weights(weights: dict[str, float] | None) -> dict[str, float]:
        if not weights:
            return {"time": 0.5, "price": 0.5}

        time_w = float(weights.get("time", 0.0))
        price_w = float(weights.get("price", 0.0))
        total = time_w + price_w

        if total <= 0:
            raise ValueError("weights must have positive total")

        return {"time": time_w / total, "price": price_w / total}
