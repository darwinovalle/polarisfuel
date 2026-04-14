from __future__ import annotations

from typing import Any


class RouteOptimizer:
    def __init__(self, geocoding_provider, directions_provider, vehicle_km_per_liter: float = 3.0):
        if vehicle_km_per_liter <= 0:
            raise ValueError("vehicle_km_per_liter must be > 0")

        self.geocoding_provider = geocoding_provider
        self.directions_provider = directions_provider
        self.vehicle_km_per_liter = float(vehicle_km_per_liter)

    def optimize(
        self,
        origin_query: str,
        destination_query: str,
        candidate_stations: list[dict[str, Any]],
        weights: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        if not candidate_stations:
            raise ValueError("candidate_stations cannot be empty")

        weights = self._normalize_weights(weights)

        origin = self.geocoding_provider.geocode(origin_query)
        destination = self.geocoding_provider.geocode(destination_query)

        baseline = self.directions_provider.route(origin, destination)

        alternatives: list[dict[str, Any]] = []
        for station in candidate_stations:
            waypoint = {
                "id": station["id"],
                "lat": station["lat"],
                "lon": station["lon"],
            }

            route_data = self.directions_provider.route(origin, destination, waypoints=[waypoint])

            distance_m = float(route_data["distance_m"])
            duration_s = float(route_data["duration_s"])
            station_price = float(station["retail_price"])
            estimated_fuel_cost = self._estimate_fuel_cost(distance_m, station_price)

            alternatives.append(
                {
                    "station": station,
                    "distance_m": distance_m,
                    "duration_s": duration_s,
                    "geometry": route_data.get("geometry", ""),
                    "estimated_fuel_cost": estimated_fuel_cost,
                }
            )

        self._apply_scores(alternatives, weights)
        alternatives.sort(key=lambda x: x["score"])

        return {
            "origin": origin,
            "destination": destination,
            "baseline_route": baseline,
            "weights": weights,
            "best_option": alternatives[0],
            "alternatives": alternatives,
        }

    def _estimate_fuel_cost(self, distance_m: float, retail_price: float) -> float:
        distance_km = distance_m / 1000.0
        liters_needed = distance_km / self.vehicle_km_per_liter
        return liters_needed * retail_price

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
