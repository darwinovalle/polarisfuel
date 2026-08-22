from __future__ import annotations

import heapq
from typing import Any

from stations.processes.fuel import calculate_fuel_metrics
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

    def _apply_scores(self, alternatives: list[dict[str, Any]], weights: dict[str, float]) -> None:
        durations = [x["duration_s"] for x in alternatives]
        prices = [x["estimated_fuel_cost"] for x in alternatives]

        min_d, max_d = min(durations), max(durations)
        min_p, max_p = min(prices), max(prices)

        for item in alternatives:
            time_norm = self._min_max_norm(item["duration_s"], min_d, max_d)
            price_norm = self._min_max_norm(item["estimated_fuel_cost"], min_p, max_p)
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
